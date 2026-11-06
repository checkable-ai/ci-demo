# The summariser service of Example Bay Advisory (a fictional sample company) on AWS Lambda, for the Checkable AI
# CI demo. Member account 726495711127, ap-southeast-2.
#
# In CI the deploy and plan jobs assume their role through GitHub OIDC (aws-actions/configure-aws-credentials), so
# the provider needs no assume_role. For a local run from the management account's admin session, pass
#   -var assume_role_arn=arn:aws:iam::726495711127:role/OrganizationAccountAccessRole
# and the provider assumes it.
#
# The bucket comes in at init time, from the TF_STATE_BUCKET repo variable in CI:
#   terraform init -backend-config="bucket=<state bucket>"

terraform {
  required_version = ">= 1.10.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.7"
    }
  }

  backend "s3" {
    key          = "checkable-ai/ci-demo/service.tfstate"
    region       = "ap-southeast-2"
    encrypt      = true
    use_lockfile = true
  }
}

provider "aws" {
  region              = var.region
  allowed_account_ids = [var.account_id]

  dynamic "assume_role" {
    for_each = var.assume_role_arn == "" ? [] : [var.assume_role_arn]
    content {
      role_arn     = assume_role.value
      session_name = "terraform-checkable-ci-demo-service"
    }
  }

  default_tags {
    tags = {
      Project    = "checkable-ci-demo"
      managed-by = "terraform"
      stack      = "ci-demo-service"
    }
  }
}
