locals {
  source_dir    = "${path.module}/../../service/summariser"
  log_group     = "/aws/lambda/${var.function_name}"
  log_group_arn = "arn:aws:logs:${var.region}:${var.account_id}:log-group:${local.log_group}"
  boundary_arn  = "arn:aws:iam::${var.account_id}:policy/${var.permissions_boundary_name}"
}

# handler.py and model.yaml, standard library only, so the package is the folder itself.
data "archive_file" "summariser" {
  type        = "zip"
  source_dir  = local.source_dir
  output_path = "${path.module}/build/summariser.zip"
  excludes    = ["__pycache__", "__pycache__/*", "**/*.pyc"]
}

# Made before the function, so Lambda never creates the group itself with no retention.
resource "aws_cloudwatch_log_group" "summariser" {
  name              = local.log_group
  retention_in_days = var.log_retention_days
}

data "aws_iam_policy_document" "assume_lambda" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [var.account_id]
    }
  }
}

# Basic logging only, to its own log group. Not the AWSLambdaBasicExecutionRole managed policy, which allows
# logs:CreateLogGroup on every group. The boundary caps the role at the same, so the deploy role cannot widen it.
resource "aws_iam_role" "exec" {
  name                 = "${var.function_name}-exec"
  description          = "Execution role for ${var.function_name}: writes its own logs, nothing else."
  assume_role_policy   = data.aws_iam_policy_document.assume_lambda.json
  permissions_boundary = local.boundary_arn
}

data "aws_iam_policy_document" "logs" {
  statement {
    effect    = "Allow"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${local.log_group_arn}:*"]
  }
}

resource "aws_iam_role_policy" "logs" {
  name   = "write-own-logs"
  role   = aws_iam_role.exec.id
  policy = data.aws_iam_policy_document.logs.json
}

resource "aws_lambda_function" "summariser" {
  function_name                  = var.function_name
  description                    = "Risky Business Solutions summariser (fictional). Dummy summaries, no AI vendor call."
  role                           = aws_iam_role.exec.arn
  runtime                        = "python3.12"
  architectures                  = ["arm64"]
  handler                        = "handler.handler"
  memory_size                    = 128
  timeout                        = 10
  reserved_concurrent_executions = var.reserved_concurrency
  filename                       = data.archive_file.summariser.output_path
  source_code_hash               = data.archive_file.summariser.output_base64sha256

  # JSON format so the platform lines (START, END, REPORT on every call) can be dropped: at WARN only errors and
  # timeouts are logged. Log ingestion is the costliest part of a public URL that gets flooded.
  logging_config {
    log_format            = "JSON"
    log_group             = aws_cloudwatch_log_group.summariser.name
    application_log_level = "INFO"
    system_log_level      = "WARN"
  }

  depends_on = [aws_iam_role_policy.logs]
}

resource "aws_lambda_function_url" "summariser" {
  function_name      = aws_lambda_function.summariser.function_name
  authorization_type = "NONE"

  cors {
    allow_origins = ["*"]
    allow_methods = ["GET", "POST"]
    allow_headers = ["content-type"]
    max_age       = 300
  }
}

# A NONE auth function URL needs both grants in the function's resource policy (Lambda's rule for URLs made from
# October 2025). Terraform, like the API and CLI, does not add them. The second one only counts for calls that come
# through the function URL.
resource "aws_lambda_permission" "url" {
  statement_id           = "FunctionUrlPublic"
  action                 = "lambda:InvokeFunctionUrl"
  function_name          = aws_lambda_function.summariser.function_name
  principal              = "*"
  function_url_auth_type = "NONE"
}

resource "aws_lambda_permission" "url_invoke" {
  statement_id             = "FunctionUrlPublicInvoke"
  action                   = "lambda:InvokeFunction"
  function_name            = aws_lambda_function.summariser.function_name
  principal                = "*"
  invoked_via_function_url = true
}
