variable "aws_region" {
  description = "AWS region for the Terraform state bucket."
  type        = string
  default     = "us-east-1"
}

variable "project_name" {
  description = "Short project identifier used in resource names."
  type        = string
  default     = "agentic-ai"
}

variable "environment" {
  description = "Bootstrap environment name."
  type        = string
  default     = "shared"
}
