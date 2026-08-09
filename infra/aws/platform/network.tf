data "aws_vpc" "lab" {
  id = var.lab_vpc_id
}

data "aws_subnet" "selected" {
  for_each = toset(var.lab_subnet_ids)

  id = each.value
}

resource "aws_security_group" "eks_nodes" {
  name        = "my-eks-cluster-cluster-agentic-sg"
  description = "Security group for Agentic AI EKS lab"
  vpc_id      = data.aws_vpc.lab.id

  egress {
    description = "Allow outbound traffic for ECR and NVIDIA API"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}
