# Checkable AI CI demo

This repository shows the Checkable feed working inside a company's own GitHub pipeline, from a vendor change in the morning to a signed-off deploy on AWS. The walkthrough and recording are at https://checkableai.com/developers/ci-demo/.

The repository belongs to Example Bay Advisory, a fictional sample company. It holds the company's AI vendor register, a small internal service that uses one of those AI plans, and the GitHub Actions that check both and deploy the service. Every name, seat count and team here is made up. The vendor changes, quotes, terms links and rules are real, taken from the Checkable feed.

What it shows:

- A vendor change that reaches a plan the company pays for becomes a pull request the same morning, opened by our GitHub App, with an email alert.
- A developer who points a service at another AI plan sees that plan's terms, the AU, EU and US rules and every open vendor change on it, in the pull request, before merge.
- A person signs each one off. Nothing merges, and nothing deploys to production, until they do.

Everything runs on GitHub-hosted runners and in your own AWS account. There is no Checkable server in the path and no API key to keep.

## The four flows

| Flow | Runs from | What it does |
|---|---|---|
| 1. Nightly check | `.github/workflows/checkable-nightly.yml` | Reads the feed, opens one pull request per vendor change that reaches the register, emails the alert through Amazon SES |
| 2. Pull request gate | `.github/workflows/checkable-gate.yml`, `.github/workflows/checkable-sign-off.yml` | Checks register, model config and Kubernetes changes, posts one comment, holds `checkable/sign-off` red until a person signs off |
| 3. CI/CD to AWS | `.github/workflows/terraform-plan.yml`, `.github/workflows/deploy.yml`, `infra/` | Posts `terraform/plan` on every pull request. After merge, `checkable/deploy-gate` matches the sign-off, then `deploy` applies to AWS Lambda in `ap-southeast-2` and smoke tests the service |
| 4. Kubernetes | `.github/workflows/k8s-policy.yml`, `k8s/` | `k8s/policy` applies the summariser manifests to a throwaway kind cluster on the runner and checks what the cluster holds against the register |

Every change to flows 3 and 4 passes the same gate as any other pull request. A pull request that changes `service/` or `infra/` needs a person's sign-off even when no AI plan changed, because those files deploy to production.

## What a run looks like

These are the results of our full rehearsal on 6 November 2026.

1. The nightly check opened pull requests #3 (GitHub makes GPT-6.1 Terra generally available in Copilot, on by default for Business) and #4 (Google turns request storage on by default for new Gemini API paid projects) as `checkable-ai[bot]`. Each showed `checkable/sign-off` red with "Waiting for a person to sign off", and an alert email from `feed@checkableai.com` arrived for each.
2. Developer pull request #5 moved `service/summariser/model.yaml` from the Gemini API paid tier to the OpenAI API platform. The gate went red with "A service uses an AI plan the register does not list". `terraform/plan` posted the plan, seven resources to add. `k8s/policy` ran its kind cluster and passed.
3. The developer added the OpenAI API to the register in the same pull request. A reviewer added the `checkable-signed-off` label and the check turned green with "Signed off by checkable-reviewer".
4. After the merge, `deploy.yml` ran `checkable/deploy-gate`, which matched the sign-off, then `deploy` in the `production` environment. Terraform created the Lambda function `checkable-ci-demo-summariser` and its function URL, the smoke test passed `GET /health` and `POST /summarise`, and the deployment shows under `production` in the repository's Deployments view.

`docs/demo-script.md` has every step, including the recorded scenario: pull request #4 signed off, then a developer moving the summariser back to the Gemini API paid tier, where the gate surfaces Google's open storage change before anything merges.

## Required checks and production approval

The ruleset on `main` requires these four checks to pass before a pull request merges:

| Check | Published by | Kind |
|---|---|---|
| `tests` | `tests.yml`, job `tests` | Check run |
| `checkable/sign-off` | `checkable-gate.yml` and `checkable-sign-off.yml` | Commit status |
| `terraform/plan` | `terraform-plan.yml`, job `terraform/plan` | Check run |
| `k8s/policy` | `k8s-policy.yml`, job `k8s/policy` | Check run |

Each one reports on every pull request, with no path filter, so no pull request waits for a check that never starts. `terraform/plan` calls AWS only when `infra/`, `service/` or its own workflow changed. `k8s/policy` starts its kind cluster only when `k8s/`, the register, the feed or its own code changed, and otherwise passes in seconds. The gate and sign-off workflows also publish job check runs named `gate` and `sign-off`. These end green once the status is posted, so `checkable/sign-off` is the result to read.

Deploys have two holds after merge. `checkable/deploy-gate` blocks any commit whose pull request lacks a matching sign-off, including a direct push. The `production` environment then waits for approval from a member of `@checkable-ai/reviewers`. The deploy role in AWS trusts only that environment, through GitHub OIDC, so the repository holds no AWS key.

## The summariser service

`service/summariser/` is a dummy internal service, a Python 3.12 Lambda handler on arm64 with 128 MB. `GET /health` returns the configured model. `POST /summarise` with `{"text": "..."}` returns a placeholder summary with the vendor, plan and model from `service/summariser/model.yaml`. It never calls an AI vendor. Since pull request #5, `model.yaml` names the register entry `openai-api`.

The function has a public function URL and no reserved concurrency, so the account's concurrency limit caps it. `infra/README.md` lists every resource, the roles and the state bucket.

## Cost

About A$0 a month at demo traffic, because the Lambda calls and logs sit inside the AWS free tier. Without the free tier it stays under A$0.05 a month. There is no NAT gateway, cloud cluster or always-on compute: the kind cluster lives on the GitHub runner for one job, and the function costs nothing while nobody calls it. GitHub Actions on a public repository is free.

## Install in your repository

1. Copy `.github/workflows/`, `.github/CODEOWNERS`, and the `scripts/`, `templates/` and `feed-snapshot/` folders into your repository.
2. Add your register as `ai-vendor-register.yaml` at the root, one entry per AI tool with the `plan` id the feed uses, and an empty `changes/` folder holding a `.gitkeep` file. Put your organisation's name in `organisation` and set `fictional: false`, or delete that line. The pull requests, change records, emails and gate comment take the name from the register.
3. Point each service's AI config at a register entry, in a flat `service/<name>/model.yaml` (`vendor`, `product`, `plan`, `model`, `register_tool`) or with the Kubernetes annotations below.
4. Create a GitHub App owned by your organisation, with repository permissions Contents, Pull requests and Issues set to read and write, and install it on the repository. Store its App ID as the secret `CHECKABLE_APP_ID` and a private key as `CHECKABLE_APP_PRIVATE_KEY`, and set the variable `CHECKABLE_BOT_LOGINS` to its bot login, for example `checkable-ai[bot]`. Pull requests the App opens start their workflows like any other. Without it the nightly check falls back to `GITHUB_TOKEN`, and GitHub then starts no workflow on those pull requests.
5. In Settings, Actions, General, keep the default workflow permissions at read. If you skip the App, also tick "Allow GitHub Actions to create and approve pull requests".
6. Create the two labels, or let the first run create them:
   ```sh
   gh label create ai-governance --color 0e8a16 --description "A vendor change from the Checkable feed"
   gh label create checkable-signed-off --color 1d76db --description "A person read the Checkable gate comment and signed this off"
   ```
7. Set the repository variable `FEED_URL` to the feed address we give you. Until it is set, every check reads `feed-snapshot/changes.json`.
8. Email is optional and runs in your own AWS account. Add the GitHub OIDC provider (`token.actions.githubusercontent.com`, audience `sts.amazonaws.com`) and a role whose trust policy accepts only the `sub` claim of your repository's `main` branch. Give the role this policy and nothing else, with your own region, account, SES identity, sender and recipients:
   ```json
   {
     "Version": "2012-10-17",
     "Statement": [{
       "Effect": "Allow",
       "Action": "ses:SendEmail",
       "Resource": "arn:aws:ses:<region>:<account-id>:identity/<your-domain>",
       "Condition": {
         "StringEquals": {"ses:FromAddress": "<sender>@<your-domain>"},
         "ForAllValues:StringEquals": {"ses:Recipients": ["<recipient>@<your-domain>"]},
         "Null": {"ses:Recipients": "false"}
       }
     }]
   }
   ```
   Store the role ARN as the secret `AWS_ROLE_ARN` and set the variables `ALERT_TO`, `ALERT_FROM` and `AWS_REGION`. Put the same addresses in `ALLOWED_TO` and `ALLOWED_FROM` at the top of `scripts/checkable/alert.py`, which checks them again before anything is sent. Without a role, the rendered emails go to the job summary.
9. For flow 3, follow the set-up in `infra/README.md`: a plan role and a deploy role through OIDC, a state bucket, and the variables `TF_PLAN_ROLE_ARN`, `TF_DEPLOY_ROLE_ARN` and `TF_STATE_BUCKET`. Create the `production` environment, limit it to `main` and add your reviewers team as required reviewers.
10. Add a ruleset on `main` that requires a pull request and the four checks above. Code owner review on top keeps a person on every path the gate guards.

Tell us what you have, and we'll help with the rest, through the enquiry form at https://checkableai.com/.

## Settings

| Setting | Purpose |
|---|---|
| `CHECKABLE_APP_ID`, `CHECKABLE_APP_PRIVATE_KEY` (secrets) | The org GitHub App the nightly check opens pull requests with. Unset, it falls back to `GITHUB_TOKEN`. |
| `CHECKABLE_BOT_LOGINS` | The App's bot login, so the gate and the deploy gate accept what it posts. `checkable-ai[bot]` in this repository. |
| `FEED_URL` | The feed file on checkableai.com. Unset, the Actions read the snapshot in this repository. |
| `ALERT_TO` | Where the alert email goes. `hello+feed-test@checkableai.com` when unset. In this demo the role accepts that address and `hello+feed-demo@checkableai.com`. |
| `ALERT_FROM` | `feed@checkableai.com` when unset, the only sender the demo role accepts. |
| `AWS_ROLE_ARN` (secret) | The role the alert job assumes through OIDC. In `checkable-ai/ci-demo` it defaults to `arn:aws:iam::726495711127:role/checkable-ci-demo-ses`. A copy of the repository sends nothing until it sets its own. |
| `AWS_REGION` | The SES region, `ap-southeast-2` when unset. |
| `TF_PLAN_ROLE_ARN`, `TF_DEPLOY_ROLE_ARN`, `TF_STATE_BUCKET` | The plan and deploy roles and the Terraform state bucket for flow 3. |

Each alert email's subject ends with the pull request number, for example "(PR #4)", so mail clients that thread by subject keep each pull request in its own thread.

GitHub pauses scheduled workflows in a repository that has had no commit for 60 days. A monthly refresh of `feed-snapshot/changes.json` keeps the nightly check running and keeps the snapshot current.

## How the gate reads a pull request

The gate code and the feed come from the base commit. The pull request's files are read through the GitHub API, so nothing from the pull request runs. The gate diffs the register by tool id and reads every changed `service/**/model.yaml` and YAML file under `k8s/`. Each tool or config is matched to the feed by plan id, or by vendor and product when it names no plan, and gets one section in a sticky comment: vendor terms, the AU, EU and US rules with one line each on why they reach a business on that plan, and every open vendor change on it. A plan the register does not list blocks sign-off until the same pull request adds it.

A person with write access adds the `checkable-signed-off` label. The gate records the sign-off against that exact commit and turns the check green. Any new commit clears it. Pull requests from forks stay red, because the sign-off has to come from inside the repository. A pull request that touches nothing the gate guards goes green straight away with "No AI tools changed".

Kubernetes manifests declare AI model use with these annotations on the resource or its pod template, or the same names as container env entries or ConfigMap keys:

| Annotation | Env or ConfigMap key |
|---|---|
| `checkable.ai/vendor` | `CHECKABLE_AI_VENDOR` |
| `checkable.ai/product` | `CHECKABLE_AI_PRODUCT` |
| `checkable.ai/plan` | `CHECKABLE_AI_PLAN` |
| `checkable.ai/model` | `CHECKABLE_AI_MODEL` |
| `checkable.ai/register-tool` | `CHECKABLE_AI_REGISTER_TOOL` |

## Tests

Unit tests under `tests/` cover the Action code, every template, the deploy gate, the Kubernetes policy and the summariser. Run them with `pip install -r scripts/requirements-dev.txt` and `python -m pytest`.

## What is in the feed

`feed-snapshot/changes.json` is a copy of the Checkable demo feed, validated by `feed-snapshot/changes.schema.json`. It carries a short catalogue of plans, each with vendor terms links and the AU, EU and US rule codes from our knowledge bases, and the latest version of each vendor change with its evidence. A quote appears only where the source page's licence allows it, and the licence is named on every quote. Where it does not, the entry carries Checkable AI's reading in our words and the link to the source.

The rules per plan and every reading are Checkable AI's reading, not legal advice. Confirm them with your adviser.

Copyright Checkable AI. All rights reserved. Vendor quotes stay under their own licence, named on each quote.
