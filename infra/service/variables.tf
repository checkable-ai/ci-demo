variable "region" {
  type    = string
  default = "ap-southeast-2"
}

variable "account_id" {
  description = "The member account the service runs in. The provider refuses any other account."
  type        = string
  default     = "726495711127"
}

variable "assume_role_arn" {
  description = "Local runs only: a role to assume first, for example OrganizationAccountAccessRole in the member account. Empty in CI."
  type        = string
  default     = ""
}

variable "function_name" {
  description = "Also fixed in the plan and deploy role policies (site repo, infra/aws/github-oidc-ses), which are scoped to it by ARN."
  type        = string
  default     = "checkable-ci-demo-summariser"
}

variable "permissions_boundary_name" {
  description = "Managed policy, made by the roles stack, that caps the execution role at writing its own logs."
  type        = string
  default     = "checkable-ci-demo-summariser-boundary"
}

variable "reserved_concurrency" {
  description = "A public URL with no auth, so at most this many copies run at once. 0 stops every call. -1 reserves none. Lambda keeps 10 unreserved, so 2 needs an account concurrency quota of at least 12 (726495711127 had 10 on 6 Nov 2026)."
  type        = number
  default     = 2
}

variable "log_retention_days" {
  type    = number
  default = 3
}
