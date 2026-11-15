#!/usr/bin/env bash
# Install k3s on the OpenTofu-provisioned VMs.
set -euo pipefail

K3S_VERSION="v1.35.10+k3s1"

SSH_OPTS=(-o StrictHostKeyChecking=accept-new -o ConnectTimeout=10)

cd "$(dirname "$0")"
TOFU=(tofu -chdir=../opentofu)
TOOLING_PUBLIC=$("${TOFU[@]}" output -raw tooling_public_ip)
TOOLING_PRIVATE=$("${TOFU[@]}" output -raw tooling_private_ip)
DATA_NODES=$("${TOFU[@]}" output -json data_private_ips |
  python3 -c 'import json, sys; print(" ".join(f"{k}={v}" for k, v in json.load(sys.stdin).items()))')

# shellcheck disable=SC2029
tooling() { ssh "${SSH_OPTS[@]}" "ubuntu@$TOOLING_PUBLIC" "$@"; }

echo "==> k3s server on tooling ($TOOLING_PRIVATE)"
tooling "curl -sfL https://get.k3s.io | sudo INSTALL_K3S_VERSION='$K3S_VERSION' sh -s - server \
  --node-ip '$TOOLING_PRIVATE' \
  --disable traefik --disable servicelb \
  --default-local-storage-path /data/k3s-storage"

echo "==> Waiting for the Kubernetes API"
tooling "until sudo k3s kubectl get --raw=/readyz >/dev/null 2>&1; do sleep 2; done"

TOKEN=$(tooling "sudo cat /var/lib/rancher/k3s/server/node-token")

count=1
for entry in $DATA_NODES; do
  name=${entry%%=*}
  ip=${entry#*=}
  echo "==> k3s agent on $name ($ip)"
  ssh "${SSH_OPTS[@]}" -J "ubuntu@$TOOLING_PUBLIC" "ubuntu@$ip" \
    "read -r TOKEN; curl -sfL https://get.k3s.io | sudo K3S_URL='https://$TOOLING_PRIVATE:6443' \
      K3S_TOKEN=\"\$TOKEN\" INSTALL_K3S_VERSION='$K3S_VERSION' sh -s - agent \
      --node-ip '$ip' \
      --node-label role=es-data \
      --node-taint dedicated=elasticsearch:NoSchedule" <<< "$TOKEN"
  count=$((count + 1))
done

echo "==> Waiting for $count nodes to be Ready"
tooling "until [ \$(sudo k3s kubectl get nodes --no-headers 2>/dev/null | wc -l) -ge $count ]; do sleep 2; done
  sudo k3s kubectl wait --for=condition=Ready node --all --timeout=180s >/dev/null
  sudo k3s kubectl get nodes -o wide -L role"
