# Flow 3: CI/CD into AWS

`infra/service/` is the Terraform for the summariser service of Example Bay Advisory (a fictional sample company): one AWS Lambda function with a public function URL, in member account 726495711127, region `ap-southeast-2`. Two workflows run it.

| Workflow | Job (check name) | When | AWS role |
| --- | --- | --- | --- |
| `.github/workflows/terraform-plan.yml` | `terraform/plan` | every pull request | `checkable-ci-demo-plan` |
| `.github/workflows/deploy.yml` | `checkable/deploy-gate`, then `deploy` | push to `main` touching `infra/service/`, `infra/scripts/`, `service/` or `deploy.yml`, and on demand from `main` | `checkable-ci-demo-deploy` |

Both roles are assumed through GitHub OIDC, so the repo holds no AWS key. They are defined outside this repo, beside the nightly's SES role, with their trust and permissions explained there.

## What `infra/service` makes

- `aws_lambda_function.summariser` (`checkable-ci-demo-summariser`): Python 3.12, arm64, 128 MB, 10 second timeout, reserved concurrency 2. The package is `service/summariser/` zipped as it is (`archive_file`, `__pycache__` left out), so `handler.py` and `model.yaml` ship together.
- `aws_lambda_function_url.summariser`: auth `NONE`, CORS for `GET` and `POST` from any origin with the `content-type` header.
- Two `aws_lambda_permission` grants, `lambda:InvokeFunctionUrl` and `lambda:InvokeFunction` (the second only for calls through the URL). Function URLs made since October 2025 need both, and Terraform does not add them.
- `aws_cloudwatch_log_group.summariser` (`/aws/lambda/checkable-ci-demo-summariser`), 3 day retention, made before the function so Lambda never makes it with no retention. JSON logs with system logs at `WARN`, so the START, END and REPORT lines are not stored.
- `aws_iam_role.exec` (`checkable-ci-demo-summariser-exec`): an inline policy for `logs:CreateLogStream` and `logs:PutLogEvents` on that log group only, and the permissions boundary `checkable-ci-demo-summariser-boundary`, which allows the same and nothing more.

Every resource carries `Project = checkable-ci-demo` through the provider's default tags. The provider refuses any account other than 726495711127. Output: `function_url`.

State: S3 backend, key `checkable-ai/ci-demo/service.tfstate`, `use_lockfile = true` (Terraform 1.10 or later, no DynamoDB table). The bucket is not in the code: CI passes it with `-backend-config="bucket=$TF_STATE_BUCKET"` from the repo variable. It is the existing Checkable AI state bucket in the management account, named in the private infrastructure repo. Its bucket policy grants the two CI roles this one key and its lock file.

## `terraform/plan`

The required check. The job's `name:` is `terraform/plan`, and GitHub names a job's check run after it, so that string is the context to require in the ruleset. Keep the name exactly as it is.

It runs on every pull request with no path filter. A required check that never starts leaves a pull request waiting forever, so the first step decides the scope instead. A pull request that changes nothing under `infra/` or `service/` (or `terraform-plan.yml` or `deploy.yml`) ends green at once with no AWS call. A fork or Dependabot pull request ends green with a note, because neither gets an OIDC token. Otherwise the job runs `terraform plan` for `infra/service` and posts it as one sticky comment (updated on every push, found by its `<!-- checkable-terraform-plan v1 -->` marker) and as the job summary. A failed plan turns the check red and the comment shows the error.

The plan role reads the function, its execution role and log group, and the state. It writes only the state lock file. A plan runs the pull request's own Terraform, so a branch author could read what that role reads. Forks cannot, and the role reaches nothing else.

## `checkable/deploy-gate` and `deploy`

No sign-off, no deploy. `checkable/deploy-gate` runs `scripts/checkable/deploy_gate.py`, which uses the Checkable gate's own constants and helpers:

1. It finds the one merged pull request into `main` whose merge commit is the commit being deployed (`GET /repos/{repo}/commits/{sha}/pulls`). A direct push has none and is blocked.
2. It reads the newest `checkable/sign-off` status on that pull request's head commit. It must be `success` and posted by the gate's bot (`github-actions[bot]`, or the org App login in `CHECKABLE_BOT_LOGINS`). A status from anyone else, or a newer status in another state, blocks the deploy.
3. A "Signed off by" status also needs the gate comment's marker to record a sign-off of that exact head commit. "No AI tools changed" needs no sign-off, the same rule as the gate. The gate gives that status only when a pull request leaves `service/` and `infra/` alone, so every change this workflow deploys was signed off by a person.

Any API error blocks the deploy too.

`deploy` then runs in the `production` environment. That gives the Deployments view and the environment URL (the function URL), and it is the only job the deploy role trusts, because its OIDC subject ends `:environment:production`. It makes a fresh plan, applies exactly that saved plan, then runs `infra/scripts/smoke.py`:

- `GET /health` must answer 200 with `status: ok`
- `POST /summarise` must answer 200 with a non-empty summary and `dummy: true`
- both must report the vendor, plan and model in `service/summariser/model.yaml`, read with the service's own parser

The job summary gives the URL, the model, the plan counts, the smoke test result and the pull request with its sign-off. The workflow's concurrency group is `production` with `cancel-in-progress: false`, so a deploy never stops halfway.

## Set-up, in order

Nothing here is applied yet.

0. Raise the Lambda concurrent executions quota in 726495711127 (Service Quotas, AWS Lambda, Concurrent executions). It was 10 on 6 Nov 2026, and Lambda keeps 10 unreserved, so the reservation of 2 fails until the quota is 12 or more. New accounts are usually raised to 1,000 on request at no charge. Until then, deploy with `reserved_concurrency = -1` (no reservation, the account limit of 10 caps it instead).

1. Create `checkable-ai/ci-demo` and read its id: `gh api repos/checkable-ai/ci-demo --jq .id`.
2. Apply the roles stack (site repo, `infra/aws/github-oidc-ses`) with `-var github_repo_id=<id>`. It makes the plan and deploy roles and the permissions boundary.
3. Apply the state bucket policy (site repo, `infra/aws/bootstrap`). It names the two roles, so it goes after step 2.
4. In this repo, set the variables `TF_STATE_BUCKET` (bootstrap output `state_bucket`), `TF_PLAN_ROLE_ARN` and `TF_DEPLOY_ROLE_ARN` (roles stack outputs).
5. Create the `production` environment and limit its deployment branches to `main`. Required reviewers on it are optional: the deploy gate already needs the Checkable sign-off.
6. Add `terraform/plan` to the ruleset's required checks.
7. Merge a signed-off pull request that touches `service/` or `infra/service/`, or run Deploy from the Actions tab on `main`.

A local run from the management account's admin session assumes `OrganizationAccountAccessRole` in the member account:

    terraform -chdir=infra/service init -backend-config="bucket=<state bucket>"
    AWS_PROFILE=checkable-admin terraform -chdir=infra/service plan -var assume_role_arn=arn:aws:iam::726495711127:role/OrganizationAccountAccessRole

## Cost at demo traffic

About A$0.00 a month: everything sits inside the AWS always-free allowances (Lambda 1 million requests and 400,000 GB-seconds a month, CloudWatch Logs 5 GB). Without them, a few thousand demo calls cost well under 1 Australian cent:

| Item | Demo use a month | Cost |
| --- | --- | --- |
| Lambda requests | 5,000 | USD 0.20 per million, under A$0.01 |
| Lambda compute, arm64 128 MB | about 50 GB-seconds | USD 0.0000133334 per GB-second, under A$0.01 |
| Function URL | | no charge |
| CloudWatch Logs, 3 days | under 1 MB (errors only) | under A$0.01 |
| State in S3 | a few KB, about 20 requests per deploy | under A$0.01 |
| IAM, OIDC, STS | | no charge |
| GitHub Actions | public repo | no charge |

There is no NAT gateway, cluster or always-on compute. The function costs nothing while nobody calls it.

The URL is public with no auth, so a flood is the one way past the A$5 a month cap. Reserved concurrency 2 limits how fast it can be called, and system logs at `WARN` keep log ingestion near zero, but request charges still grow with traffic. Set `reserved_concurrency` to 0 to stop every call, or remove the URL, if that ever happens. The organisation's budget brake does not stop calls to a function that already exists.
