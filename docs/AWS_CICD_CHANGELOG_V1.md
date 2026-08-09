# AWS CI/CD V1 Change Manifest

## Agentic AI repo

- `Dockerfile.aws`: production-oriented image without operational/lakehouse data.
- `.dockerignore`: excludes local secrets and local lakehouse artifacts.
- `cicd/`: CodeBuild quality, immutable image, staging/prod deployment, and live AI evaluation gates.
- `deploy/helm/agentic-ai/`: staging/prod Helm deployment, probes, resources, PDB and optional HPA.
- `deploy/k8s/`: PostgreSQL migration, staging ingestion, and staging-to-prod index-promotion Jobs.
- `scripts/migrate_postgres.py`: RDS-compatible role/migration bootstrap.
- `scripts/aws/put_runtime_secret.sh`: sends NVIDIA/runtime credentials to Secrets Manager without printing values.
- `scripts/aws/bootstrap_cluster.sh`: creates namespaces and EFS-backed PVCs.
- `scripts/aws/create_cognito_test_user.sh`: production JWT test helper.
- `infra/aws/bootstrap/`: KMS-encrypted/versioned S3 Terraform backend with S3 lockfile support.
- `infra/aws/platform/`: VPC, private EKS nodes, ECR, RDS PostgreSQL, EFS, KMS, Secrets Manager, Cognito, CodeBuild, CodePipeline and namespace-scoped EKS deployment access.
- `ops/sql/001_enterprise_schema.sql`: RDS-compatible registry RLS policy adjustment.

## DCEA repo

- `Dockerfile.aws`: Java/PySpark/Delta cloud image with Delta JVM dependencies warmed during build.
- `cicd/`: quality, immutable ECR build and medallion deployment buildspecs.
- `deploy/helm/dcea-data/`: suspended CronJob used as the versioned Job template.
- `scripts/run_medallion_aws.py`: cloud-safe medallion execution without deleting the published Delta warehouse.
- `src/dcea_associate_demo/delta_io.py`: safe Delta overwrite mode preserving transaction-log history in AWS mode.
