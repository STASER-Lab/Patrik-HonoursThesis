#!/usr/bin/env bash
# Install the ECK operator on the k3s cluster.
set -euo pipefail

ECK_VERSION="3.5.0"

SSH_OPTS=(-o StrictHostKeyChecking=accept-new -o ConnectTimeout=10)

cd "$(dirname "$0")"
TOOLING_PUBLIC=$(tofu -chdir=../opentofu output -raw tooling_public_ip)

ssh "${SSH_OPTS[@]}" "ubuntu@$TOOLING_PUBLIC" bash -s -- "$ECK_VERSION" <<'REMOTE'
set -euo pipefail
BASE="https://download.elastic.co/downloads/eck/$1"
k() { sudo k3s kubectl "$@"; }

echo "==> ECK $1: custom resource definitions"
k apply --server-side -f "$BASE/crds.yaml"

echo "==> ECK $1: operator"
k apply -f "$BASE/operator.yaml"

echo "==> Pinning the operator to the control-plane node"
k -n elastic-system patch statefulset elastic-operator --type merge \
  -p '{"spec":{"template":{"spec":{"nodeSelector":{"node-role.kubernetes.io/control-plane":"true"}}}}}'

echo "==> Waiting for the operator"
k -n elastic-system rollout status statefulset/elastic-operator --timeout=180s
k -n elastic-system get pods -o wide
REMOTE
