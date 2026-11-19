#!/usr/bin/env bash
# Prepare the tooling VM to run the project's Python code against the cluster.
set -euo pipefail

REPO_URL="https://github.com/STASER-Lab/Patrik-HonoursThesis.git"
SSH_OPTS=(-o StrictHostKeyChecking=accept-new -o ConnectTimeout=10)

cd "$(dirname "$0")"
TOOLING_PUBLIC=$(tofu -chdir=../opentofu output -raw tooling_public_ip)

ssh "${SSH_OPTS[@]}" "ubuntu@$TOOLING_PUBLIC" bash -s -- "$REPO_URL" <<'REMOTE'
set -euo pipefail
REPO_URL=$1
REPO=/data/Patrik-HonoursThesis
k() { sudo k3s kubectl "$@"; }

echo "==> Python 3.14"
if ! command -v python3.14 >/dev/null; then
  sudo add-apt-repository -y ppa:deadsnakes/ppa
  sudo apt-get install -y python3.14 python3.14-venv
fi

echo "==> Repository in $REPO"
sudo install -d -o ubuntu -g ubuntu "$REPO"
if [ -d "$REPO/.git" ]; then
  git -C "$REPO" pull --ff-only
else
  git clone "$REPO_URL" "$REPO"
fi
cd "$REPO"
[ -d .venv ] || python3.14 -m venv .venv
.venv/bin/pip install -q -r requirements.lock
.venv/bin/pip install -q -e . --no-deps

echo "==> Rally: Python 3.13 + esrally 2.13.0 in ~/.venvs/esrally"
# esrally does not support Python 3.14 yet, so it gets its own venv
if ! command -v python3.13 >/dev/null; then
  sudo add-apt-repository -y ppa:deadsnakes/ppa
  sudo apt-get install -y python3.13 python3.13-venv
fi
[ -d ~/.venvs/esrally ] || python3.13 -m venv ~/.venvs/esrally
~/.venvs/esrally/bin/pip install -q esrally==2.13.0
~/.venvs/esrally/bin/esrally --version

echo "==> Elasticsearch connection settings in ~/es.env"
ES_HOST=hons-es-http.default.svc
ES_IP=$(k get svc hons-es-http -o jsonpath='{.spec.clusterIP}')
sudo sed -i "/ $ES_HOST\$/d" /etc/hosts
echo "$ES_IP $ES_HOST" | sudo tee -a /etc/hosts >/dev/null

install -d -m 700 ~/.es
k get secret hons-es-http-certs-public -o go-template='{{index .data "ca.crt" | base64decode}}' > ~/.es/ca.crt
PASSWORD=$(k get secret hons-es-elastic-user -o go-template='{{.data.elastic | base64decode}}')
umask 077
cat > ~/es.env <<ENV
export ES_URL=https://$ES_HOST:9200
export ES_USER=elastic
export ES_PASSWORD=$PASSWORD
export ES_CA_CERTS=$HOME/.es/ca.crt
ENV

echo "==> Connecting with ingest.load.connect.client()"
# shellcheck disable=SC1090
source ~/es.env
.venv/bin/python -c "from ingest.load.connect import client; v = client().info()['version']; print('Connected to Elasticsearch', v['number'])"
REMOTE
