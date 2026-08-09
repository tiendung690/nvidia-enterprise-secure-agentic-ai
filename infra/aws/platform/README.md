# AWS Platform Terraform

This stack creates a cost-aware EKS CI/CD platform for the two-repository DCEA + Enterprise Secure Agentic AI lab:

- VPC with public/private subnets across 2-3 AZs
- EKS managed node group on private subnets
- ECR repositories with immutable tags
- RDS PostgreSQL with AWS-managed master password in Secrets Manager
- EFS access points for staging/prod RAG indexes and shared Delta Gold data
- Cognito user pool for production JWTs
- CodeBuild + CodePipeline for both repositories
- namespace-scoped EKS access for the deployment role
- encrypted S3 artifact/data buckets and KMS keys

## Why one EKS cluster?

The hands-on version uses one cluster with `agentic-staging`, `agentic-prod`, and `data-platform` namespaces to limit lab cost. A high-isolation enterprise target should separate non-production and production into different AWS accounts and normally separate clusters.

## Order of operations

1. Run `../bootstrap` to create the Terraform remote-state bucket.
2. Create and authorize an AWS CodeConnections GitHub connection.
3. Copy `terraform.tfvars.example` to `terraform.tfvars` and fill owner, connection ARN, and trusted public CIDR.
4. `terraform init -backend-config=backend.hcl`
5. `terraform plan`
6. `terraform apply`
7. Populate the runtime secret with `./scripts/aws/put_runtime_secret.sh` from repo root.
8. Bootstrap namespaces/PV/PVC with `./scripts/aws/bootstrap_cluster.sh` from repo root.
9. Push both repositories to the configured GitHub branches.
10. CodePipeline builds and deploys automatically.

The Agentic pipeline builds once and promotes the exact ECR digest from staging to production. Staging performs the NVIDIA-backed RAG ingestion and live AI quality suite. After manual approval, the already-built staging RAG indexes are copied to the isolated production EFS access point, avoiding a second NVIDIA embedding bill/quota hit.
