#!/usr/bin/env bash
set -euo pipefail

: "${AWS_REGION:=ap-southeast-1}"
: "${TEST_EMAIL:?Set TEST_EMAIL}"
: "${TEST_PASSWORD:?Set TEST_PASSWORD to a strong temporary/local lab password}"
TF_DIR=${TF_DIR:-infra/aws/platform}
POOL_ID=${COGNITO_USER_POOL_ID:-$(terraform -chdir="$TF_DIR" output -raw cognito_user_pool_id)}
CLIENT_ID=${COGNITO_CLIENT_ID:-$(terraform -chdir="$TF_DIR" output -raw cognito_client_id)}

aws cognito-idp admin-create-user --region "$AWS_REGION" --user-pool-id "$POOL_ID" \
  --username "$TEST_EMAIL" \
  --user-attributes \
    Name=email,Value="$TEST_EMAIL" \
    Name=email_verified,Value=true \
    Name=custom:tenant_id,Value=tenant-a \
    Name=custom:clearance,Value=internal \
    Name=custom:authz_version,Value=1 \
    Name=custom:departments,Value=engineering \
  --message-action SUPPRESS >/dev/null 2>&1 || true

aws cognito-idp admin-set-user-password --region "$AWS_REGION" --user-pool-id "$POOL_ID" \
  --username "$TEST_EMAIL" --password "$TEST_PASSWORD" --permanent

aws cognito-idp create-group --region "$AWS_REGION" --user-pool-id "$POOL_ID" --group-name analyst >/dev/null 2>&1 || true
aws cognito-idp admin-add-user-to-group --region "$AWS_REGION" --user-pool-id "$POOL_ID" \
  --username "$TEST_EMAIL" --group-name analyst

echo "Cognito test user ready. Obtain an ID token with:"
echo "aws cognito-idp admin-initiate-auth --region $AWS_REGION --user-pool-id $POOL_ID --client-id $CLIENT_ID --auth-flow ADMIN_USER_PASSWORD_AUTH --auth-parameters USERNAME=$TEST_EMAIL,PASSWORD='<password>' --query 'AuthenticationResult.IdToken' --output text"
