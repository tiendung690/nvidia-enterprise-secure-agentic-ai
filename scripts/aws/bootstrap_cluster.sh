#!/usr/bin/env bash
set -euo pipefail

: "${AWS_REGION:=ap-southeast-1}"
TF_DIR=${TF_DIR:-infra/aws/platform}
CLUSTER_NAME=${EKS_CLUSTER_NAME:-$(terraform -chdir="$TF_DIR" output -raw eks_cluster_name)}
EFS_ID=$(terraform -chdir="$TF_DIR" output -raw efs_file_system_id)
RAG_STAGING_AP=$(terraform -chdir="$TF_DIR" output -raw efs_rag_staging_access_point_id)
RAG_PROD_AP=$(terraform -chdir="$TF_DIR" output -raw efs_rag_prod_access_point_id)
LAKEHOUSE_AP=$(terraform -chdir="$TF_DIR" output -raw efs_lakehouse_access_point_id)

aws eks update-kubeconfig --region "$AWS_REGION" --name "$CLUSTER_NAME"

for ns in agentic-staging agentic-prod data-platform; do
  kubectl create namespace "$ns" --dry-run=client -o yaml | kubectl apply -f -
done

cat <<YAML | kubectl apply -f -
apiVersion: v1
kind: PersistentVolume
metadata:
  name: agentic-rag-staging-pv
spec:
  capacity: { storage: 20Gi }
  volumeMode: Filesystem
  accessModes: ["ReadWriteMany"]
  persistentVolumeReclaimPolicy: Retain
  storageClassName: efs-static
  mountOptions: ["tls"]
  csi:
    driver: efs.csi.aws.com
    volumeHandle: ${EFS_ID}::${RAG_STAGING_AP}
---
apiVersion: v1
kind: PersistentVolume
metadata:
  name: agentic-rag-staging-copy-pv
spec:
  capacity: { storage: 20Gi }
  volumeMode: Filesystem
  accessModes: ["ReadWriteMany"]
  persistentVolumeReclaimPolicy: Retain
  storageClassName: efs-static
  mountOptions: ["tls"]
  csi:
    driver: efs.csi.aws.com
    volumeHandle: ${EFS_ID}::${RAG_STAGING_AP}
---
apiVersion: v1
kind: PersistentVolume
metadata:
  name: agentic-rag-prod-pv
spec:
  capacity: { storage: 20Gi }
  volumeMode: Filesystem
  accessModes: ["ReadWriteMany"]
  persistentVolumeReclaimPolicy: Retain
  storageClassName: efs-static
  mountOptions: ["tls"]
  csi:
    driver: efs.csi.aws.com
    volumeHandle: ${EFS_ID}::${RAG_PROD_AP}
---
apiVersion: v1
kind: PersistentVolume
metadata:
  name: agentic-lakehouse-staging-pv
spec:
  capacity: { storage: 50Gi }
  volumeMode: Filesystem
  accessModes: ["ReadWriteMany"]
  persistentVolumeReclaimPolicy: Retain
  storageClassName: efs-static
  mountOptions: ["tls"]
  csi:
    driver: efs.csi.aws.com
    volumeHandle: ${EFS_ID}::${LAKEHOUSE_AP}
---
apiVersion: v1
kind: PersistentVolume
metadata:
  name: agentic-lakehouse-prod-pv
spec:
  capacity: { storage: 50Gi }
  volumeMode: Filesystem
  accessModes: ["ReadWriteMany"]
  persistentVolumeReclaimPolicy: Retain
  storageClassName: efs-static
  mountOptions: ["tls"]
  csi:
    driver: efs.csi.aws.com
    volumeHandle: ${EFS_ID}::${LAKEHOUSE_AP}
---
apiVersion: v1
kind: PersistentVolume
metadata:
  name: dcea-lakehouse-pv
spec:
  capacity: { storage: 50Gi }
  volumeMode: Filesystem
  accessModes: ["ReadWriteMany"]
  persistentVolumeReclaimPolicy: Retain
  storageClassName: efs-static
  mountOptions: ["tls"]
  csi:
    driver: efs.csi.aws.com
    volumeHandle: ${EFS_ID}::${LAKEHOUSE_AP}
YAML

cat <<'YAML' | kubectl -n agentic-staging apply -f -
apiVersion: v1
kind: PersistentVolumeClaim
metadata: { name: agentic-rag-storage }
spec:
  accessModes: ["ReadWriteMany"]
  storageClassName: efs-static
  volumeName: agentic-rag-staging-pv
  resources: { requests: { storage: 20Gi } }
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata: { name: agentic-lakehouse }
spec:
  accessModes: ["ReadWriteMany"]
  storageClassName: efs-static
  volumeName: agentic-lakehouse-staging-pv
  resources: { requests: { storage: 50Gi } }
YAML

cat <<'YAML' | kubectl -n agentic-prod apply -f -
apiVersion: v1
kind: PersistentVolumeClaim
metadata: { name: agentic-rag-storage }
spec:
  accessModes: ["ReadWriteMany"]
  storageClassName: efs-static
  volumeName: agentic-rag-prod-pv
  resources: { requests: { storage: 20Gi } }
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata: { name: agentic-rag-staging-source }
spec:
  accessModes: ["ReadWriteMany"]
  storageClassName: efs-static
  volumeName: agentic-rag-staging-copy-pv
  resources: { requests: { storage: 20Gi } }
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata: { name: agentic-lakehouse }
spec:
  accessModes: ["ReadWriteMany"]
  storageClassName: efs-static
  volumeName: agentic-lakehouse-prod-pv
  resources: { requests: { storage: 50Gi } }
YAML

cat <<'YAML' | kubectl -n data-platform apply -f -
apiVersion: v1
kind: PersistentVolumeClaim
metadata: { name: dcea-lakehouse }
spec:
  accessModes: ["ReadWriteMany"]
  storageClassName: efs-static
  volumeName: dcea-lakehouse-pv
  resources: { requests: { storage: 50Gi } }
YAML

kubectl get pvc -A
