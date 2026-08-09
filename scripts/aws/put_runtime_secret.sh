#!/usr/bin/env bash
set -euo pipefail

: "${AWS_REGION:=ap-southeast-1}"
: "${NVIDIA_API_KEY:?Export NVIDIA_API_KEY before running this script}"

SECRET_ID=${RUNTIME_SECRET_ID:-$(terraform -chdir=infra/aws/platform output -raw runtime_secret_arn)}

python - <<'PY' > /tmp/agentic-runtime.json
import json, os, secrets

def secure(n=32):
    return secrets.token_urlsafe(n)

print(json.dumps({
    "NVIDIA_API_KEY": os.environ["NVIDIA_API_KEY"],
    "ADMIN_TOKEN": secure(32),
    "MASKING_SALT": secure(32),
    "DB_APP_PASSWORD": secure(28),
    "DB_REGISTRY_PASSWORD": secure(28),
}))
PY

aws secretsmanager put-secret-value \
  --region "$AWS_REGION" \
  --secret-id "$SECRET_ID" \
  --secret-string file:///tmp/agentic-runtime.json >/dev/null
rm -f /tmp/agentic-runtime.json

echo "Runtime secret populated: $SECRET_ID"
echo "No secret values were printed."
