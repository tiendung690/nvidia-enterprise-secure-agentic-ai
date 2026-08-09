# Terraform bootstrap

This stack creates only the encrypted/versioned S3 remote-state bucket and KMS key.
It intentionally uses local state because the remote backend does not exist yet.

```bash
terraform init
terraform apply
terraform output -raw backend_hcl > ../platform/backend.hcl
```

The platform stack then uses S3 native lock files (`use_lockfile = true`).
