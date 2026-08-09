# AWS CI/CD Deployment Guide V1 — DCEA + Enterprise Secure Agentic AI

## Target flow

```text
GitHub Agentic repo
  -> CodePipeline
  -> CodeBuild quality gate
  -> build Docker once
  -> ECR immutable commit tag + vulnerability gate
  -> staging EKS
       -> DB migration Job
       -> RAG ingestion Job (NVIDIA embedding once)
       -> Helm rolling deployment
       -> /health live + ready
       -> live golden Agentic AI evaluation
  -> manual approval
  -> copy the exact staging RAG index to isolated prod EFS
  -> prod EKS using the exact same ECR digest

GitHub DCEA repo
  -> CodePipeline
  -> compile/contract gate
  -> ECR immutable image
  -> Helm CronJob
  -> one medallion Job run
  -> Delta Bronze/Silver/Gold on shared EFS
  -> Agentic staging/prod read curated Gold only
```

## Deliberate V1 boundaries

- One EKS cluster is used to control hands-on cost; staging and production are separate namespaces and RAG EFS access points.
- The Agentic API Service is ClusterIP-only in V1. Validate from a controlled port-forward or private network. Put AWS Load Balancer Controller + ALB/WAF/TLS in front before exposing this publicly.
- The DCEA image contains deterministic sample source data because this is the interview lab. Real production source data should arrive from S3/Databricks/source systems, not Git.
- Local RabbitMQ remains the deep MQ mechanics lab. The next AWS messaging phase should replace broker adapters with EventBridge/SQS without changing business contracts.

## 0. Prerequisites

Install/configure:

```bash
aws --version
terraform version
kubectl version --client
helm version
aws sts get-caller-identity
```

Use an AWS identity allowed to create VPC/EKS/IAM/KMS/RDS/EFS/ECR/CodeBuild/CodePipeline/Cognito/Secrets Manager resources.

## 1. Push both repositories to GitHub

The pipeline assumes two GitHub repositories:

```text
nvidia-enterprise-secure-agentic-ai
dcea_demo
```

Never push `.env`, `.env.bak`, NVIDIA keys, AWS keys, DB passwords, or JWT secrets.

## 2. Create/authorize one AWS CodeConnections GitHub connection

In AWS Console:

```text
Developer Tools -> Settings -> Connections -> Create connection -> GitHub
```

Complete the GitHub App authorization until the connection is `AVAILABLE`. Copy its ARN into `terraform.tfvars`.

## 3. Bootstrap remote Terraform state

From the Agentic repository root:

```bash
cd infra/aws/bootstrap
cp terraform.tfvars.example terraform.tfvars
terraform init
terraform fmt -check
terraform validate
terraform plan
terraform apply
terraform output -raw backend_hcl > ../platform/backend.hcl
cd ../../..
```

## 4. Configure platform variables

```bash
cd infra/aws/platform
cp terraform.tfvars.example terraform.tfvars
nano terraform.tfvars
```

At minimum replace:

```hcl
github_owner = "YOUR_GITHUB_USER"
codestar_connection_arn = "arn:aws:codeconnections:..."
cluster_public_access_cidrs = ["YOUR_CURRENT_PUBLIC_IP/32"]
```

For the cheapest useful lab keep:

```hcl
az_count        = 2
nat_gateway_mode = "single"
rds_multi_az    = false
```

For a stronger HA architecture use `terraform.production.tfvars.example` as the starting point.

## 5. Provision AWS platform

```bash
terraform init -backend-config=backend.hcl
terraform fmt -check
terraform validate
terraform plan -out=tfplan
terraform apply tfplan
```

Useful outputs:

```bash
terraform output
```

## 6. Populate runtime Secrets Manager value

Terraform creates the secret container but intentionally never receives the NVIDIA key or generated application passwords.

From repo root:

```bash
export AWS_REGION=ap-southeast-1
export NVIDIA_API_KEY='nvapi-...'
./scripts/aws/put_runtime_secret.sh
unset NVIDIA_API_KEY
```

The script generates `ADMIN_TOKEN`, `MASKING_SALT`, `DB_APP_PASSWORD`, and `DB_REGISTRY_PASSWORD` locally and sends them directly to Secrets Manager without printing them.

## 7. Bootstrap Kubernetes namespaces and persistent storage

Run once with the same AWS identity that created the cluster:

```bash
./scripts/aws/bootstrap_cluster.sh
```

Expected:

```text
agentic-staging/agentic-rag-storage   Bound
agentic-staging/agentic-lakehouse     Bound
agentic-prod/agentic-rag-storage      Bound
agentic-prod/agentic-rag-staging-source Bound
agentic-prod/agentic-lakehouse        Bound
data-platform/dcea-lakehouse          Bound
```

## 8. Run DCEA pipeline first

A push to the DCEA configured branch automatically starts CodePipeline. Or start it manually:

```bash
PIPE=$(terraform -chdir=infra/aws/platform output -raw dcea_pipeline_name)
aws codepipeline start-pipeline-execution --name "$PIPE"
```

Watch:

```bash
aws codepipeline get-pipeline-state --name "$PIPE"
```

After success:

```bash
aws eks update-kubeconfig --region ap-southeast-1 --name "$(terraform -chdir=infra/aws/platform output -raw eks_cluster_name)"
kubectl -n data-platform get jobs
kubectl -n data-platform get cronjob dcea-medallion
```

DCEA AWS mode does **not** `shutil.rmtree()` the Delta table before overwrite. It lets Delta commit a new version so an Agentic reader never sees a deliberately deleted Gold directory between releases.

## 9. Run Agentic pipeline

A push to the Agentic branch starts:

```text
Source
 -> Quality
 -> Build immutable image + scan
 -> Staging deploy
 -> Agentic AI golden evaluation
 -> Manual approval
 -> Production deploy same digest
```

Manual start:

```bash
PIPE=$(terraform -chdir=infra/aws/platform output -raw agentic_pipeline_name)
aws codepipeline start-pipeline-execution --name "$PIPE"
```

The staging deploy:

1. reads AWS Secrets Manager values,
2. creates namespace-scoped Kubernetes secrets,
3. runs DB migration,
4. rebuilds RAG index using NVIDIA embeddings,
5. deploys with Helm,
6. runs live/readiness smoke checks,
7. runs `scripts/evaluate_api.py` as the AI quality gate.

Production is blocked until manual approval. Production does **not** rebuild the Docker image or call the embedding API again. It copies the staging-passed RAG index to the isolated production access point and deploys the same ECR digest.

## 10. Verify EKS

```bash
kubectl -n agentic-staging get deploy,pod,svc,jobs
kubectl -n agentic-prod get deploy,pod,svc,jobs
kubectl -n data-platform get cronjob,jobs,pod
```

Verify image digest:

```bash
kubectl -n agentic-staging get deploy agentic-ai -o jsonpath='{.spec.template.spec.containers[0].image}'; echo
kubectl -n agentic-prod get deploy agentic-ai -o jsonpath='{.spec.template.spec.containers[0].image}'; echo
```

The two values must be identical after production promotion.

## 11. Test staging API from your workstation

```bash
kubectl -n agentic-staging port-forward svc/agentic-ai 8000:8000
```

Another terminal:

```bash
curl -fsS http://127.0.0.1:8000/health/live
curl -fsS http://127.0.0.1:8000/health/ready
```

Then run a dev-identity request:

```bash
curl -s http://127.0.0.1:8000/v1/chat \
  -H 'Content-Type: application/json' \
  -H 'X-User-Id: aws-lab' \
  -H 'X-Tenant-Id: public' \
  -H 'X-Clearance: public' \
  -d '{"query":"Using only the indexed Agentic RAG course, explain the four core agent components and cite the evidence.","session_id":"aws-staging-001","force_retrieval":true}'
```

## 12. Test production Cognito JWT

Create a lab user:

```bash
export TEST_EMAIL='you@example.com'
export TEST_PASSWORD='Use-A-Strong-Temporary-Password!1'
./scripts/aws/create_cognito_test_user.sh
unset TEST_PASSWORD
```

Obtain the ID token using the command printed by the script, then:

```bash
kubectl -n agentic-prod port-forward svc/agentic-ai 8001:8000
curl -s http://127.0.0.1:8001/v1/chat \
  -H "Authorization: Bearer $ID_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"query":"What is the highest-revenue book?","session_id":"prod-jwt-001","purpose":"business-analytics","answer_mode":"enterprise_factual"}'
```

## 13. Rollback

Because ECR tags are immutable and Helm deploys a digest, rollback identifies a precise artifact.

```bash
helm -n agentic-prod history agentic-ai
helm -n agentic-prod rollback agentic-ai <REVISION> --wait
```

For a full release rollback, rerun CodePipeline from the desired Git commit or explicitly deploy the previous known-good digest after the same approval controls.

## 14. Cost control after practice

The stack contains billable EKS, EC2 worker nodes, NAT Gateway, RDS, EFS, CodeBuild, S3/KMS, and other AWS resources. When the lab is no longer needed, clean it up deliberately. If you configured RDS deletion protection/final snapshots, handle those first.

Do not destroy the state bootstrap bucket until the platform stack is already destroyed and you have intentionally retained/exported any state you still need.
