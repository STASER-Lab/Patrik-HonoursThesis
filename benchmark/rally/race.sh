#!/bin/bash
# Run one Rally race against the cluster, with the connection settings from ~/es.env.
set -euo pipefail

if [ $# -lt 2 ]; then
  sed -n '4,5p' "$0" >&2
  exit 2
fi
: "${ES_URL:?run 'source ~/es.env' first}"
: "${ES_USER:?run 'source ~/es.env' first}"
: "${ES_PASSWORD:?run 'source ~/es.env' first}"
: "${ES_CA_CERTS:?run 'source ~/es.env' first}"

params=$1 report=$2
shift 2
repo=$(cd "$(dirname "$0")/../.." && pwd)

exec "${ESRALLY:-$HOME/.venvs/esrally/bin/esrally}" race --pipeline=benchmark-only \
  --track-path="$repo/benchmark/rally/track" --track-params="$params" \
  --target-hosts="${ES_URL#*://}" \
  --client-options="use_ssl:true,verify_certs:true,ca_certs:'$ES_CA_CERTS',basic_auth_user:'$ES_USER',basic_auth_password:'$ES_PASSWORD'" \
  --report-file="$report" --on-error=abort "$@"
