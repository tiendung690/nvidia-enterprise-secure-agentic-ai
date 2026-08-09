output "state_bucket" {
  value = aws_s3_bucket.terraform_state.bucket
}

output "backend_hcl" {
  value = <<-EOT
bucket       = "${aws_s3_bucket.terraform_state.bucket}"
key          = "platform/terraform.tfstate"
region       = "${var.aws_region}"
encrypt      = true
use_lockfile = true
EOT
}
