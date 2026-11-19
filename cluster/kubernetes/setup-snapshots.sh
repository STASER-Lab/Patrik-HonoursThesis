#!/usr/bin/env bash
# Create the Elasticsearch cluster connected to the snapshot bucket in cluster/storage.
set -euo pipefail

SSH_OPTS=(-o StrictHostKeyChecking=accept-new -o ConnectTimeout=10)

cd "$(dirname "$0")"
TOOLING_PUBLIC=$(tofu -chdir=../opentofu output -raw tooling_public_ip)
BUCKET=$(tofu -chdir=../storage output -raw bucket_name)
[ -n "$BUCKET" ] || { echo "No bucket name" >&2; exit 1; }
KEYS_FILE="$HOME/.config/openstack/s3-keys.json"
[ -f "$KEYS_FILE" ] || { echo "Missing $KEYS_FILE" >&2; exit 1; }
# shellcheck disable=SC2029
tooling() { ssh "${SSH_OPTS[@]}" "ubuntu@$TOOLING_PUBLIC" "$@"; }

echo "==> S3 keys -> Kubernetes secret hons-s3-credentials"
# shellcheck disable=SC2016
python3 -c '
import json, sys
k = json.load(open(sys.argv[1]))
print(json.dumps({
    "apiVersion": "v1", "kind": "Secret",
    "metadata": {"name": "hons-s3-credentials"},
    "stringData": {
        "s3.client.default.access_key": k["access"],
        "s3.client.default.secret_key": k["secret"],
    },
}))' "$KEYS_FILE" | tooling sudo k3s kubectl apply -f -

echo "==> Applying elasticsearch.yaml"
tooling sudo k3s kubectl apply -f - < elasticsearch.yaml

echo "==> Registering snapshot repository 'hons' (bucket $BUCKET)"
tooling bash -s -- "$BUCKET" <<'REMOTE'
set -euo pipefail
k() { sudo k3s kubectl "$@"; }
HOST=hons-es-http.default.svc
CA=$(mktemp)
trap 'rm -f "$CA"' EXIT
es() {
  local ip pw
  ip=$(k get svc hons-es-http -o jsonpath='{.spec.clusterIP}') || return 1
  pw=$(k get secret hons-es-elastic-user -o go-template='{{.data.elastic | base64decode}}') || return 1
  k get secret hons-es-http-certs-public -o go-template='{{index .data "ca.crt" | base64decode}}' > "$CA" || return 1
  curl -sS --cacert "$CA" --resolve "$HOST:9200:$ip" -u "elastic:$pw" \
    -H 'Content-Type: application/json' "$@"
}
out=""
for attempt in $(seq 1 60); do
  out=$(es -X PUT "https://$HOST:9200/_snapshot/hons" -d "{\"type\":\"s3\",\"settings\":{\"bucket\":\"$1\"}}" 2>&1) || true
  if echo "$out" | grep -q '"acknowledged":true'; then
    echo "Registered."
    es -X POST "https://$HOST:9200/_snapshot/hons/_verify?pretty"
    exit 0
  fi
  echo "  not yet (attempt $attempt): $(echo "$out" | head -c 200)"
  sleep 20
done
echo "Gave up after 20 minutes. Last response: $out" >&2
exit 1
REMOTE
