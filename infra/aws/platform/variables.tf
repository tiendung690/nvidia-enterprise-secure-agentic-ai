variable "aws_region" {
  type    = string
  default = "us-east-1"
}

variable "project_name" {
  type    = string
  default = "agentic-ai"
}

variable "environment" {
  type    = string
  default = "lab"
}

variable "lab_vpc_id" {
  type    = string
  default = "vpc-09005c70dc1128f97"
}

variable "lab_subnet_ids" {
  type = list(string)

  default = [
    "subnet-054b13d4df886ffde",
    "subnet-0907b5d62fc7696ab"
  ]
}

variable "kubernetes_version" {
  type    = string
  default = "1.36"
}

variable "node_instance_types" {
  type = list(string)

  default = [
    "t3.medium"
  ]
}

variable "node_min_size" {
  type    = number
  default = 1
}

variable "node_desired_size" {
  type    = number
  default = 1
}

variable "node_max_size" {
  type    = number
  default = 2
}

variable "cluster_public_access_cidrs" {
  type = list(string)

  default = [
    "0.0.0.0/0"
  ]
}
