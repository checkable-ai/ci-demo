# Checkable AI CI demo

This repository shows the Checkable feed working inside a company's own GitHub pipeline. It holds the AI vendor register of Example Bay Advisory, a fictional sample company, a small internal service that uses one of those AI tools, and the GitHub Actions that keep both checked. Every name, seat count and team here is made up. The vendor changes, quotes, terms links and rules are real, taken from the Checkable feed.

What it shows:

- A vendor change that reaches a tool you pay for turns into a pull request the same morning, with the vendor's words where the licence allows, the source link, what to do and a sign-off checklist. The same alert goes out by email through Amazon SES.
- A developer who adds an AI tool, or points a service at a different AI vendor plan, gets the vendor's terms, the AU, EU and US rules for that plan and every open vendor change on it, in the pull request, before merge.
- A person signs each one off. The `checkable/sign-off` check stays red until they do.

Everything runs on GitHub-hosted runners. There is no server to host and no API key to keep.

## The four flows

| Flow | Runs from | What it does |
|---|---|---|
| 1. Nightly check | `.github/workflows/checkable-nightly.yml` | Reads the feed, opens one pull request per vendor change that reaches the register, emails the alert |
| 2. Pull request gate | `.github/workflows/checkable-gate.yml`, `.github/workflows/checkable-sign-off.yml` | Checks register, model config and Kubernetes changes, posts one comment, holds `checkable/sign-off` red until a person signs off |
| 3. CI/CD to AWS | `.github/workflows/deploy.yml`, `infra/` | Plans and deploys the summariser service to AWS Lambda in `ap-southeast-2`, with `terraform/plan` on every pull request |
| 4. Kubernetes | `k8s/` | Manifests for the summariser, checked by `k8s/policy` and read by the gate for AI model use |

Flows 3 and 4 live at reserved paths, `.github/workflows/deploy.yml`, `infra/` and `k8s/`, and every change to them passes the same gate as any other pull request.

### Flow 1: the nightly check

`checkable-nightly.yml` runs at 21:00 UTC (8am in Sydney during daylight saving) and on demand from the Actions tab.

1. It loads the feed from the `FEED_URL` variable, or from `feed-snapshot/changes.json` when that is unset. The snapshot is the same file.
2. It matches every change in the feed against every tool in the register by plan id. A change reaches the register when at least one tool is affected or worth a check. Vendor names alone never match.
3. For each reaching change it opens one pull request on the branch `checkable/<change_id>`, adding one file, `changes/<change_id>.md`. The register itself is never edited by the nightly check. One change id opens one pull request, ever. When the vendor moves again and the feed carries a higher version, the nightly check updates the open pull request or comments on the merged one.
4. It opens the pull request with a token from the org's GitHub App, Checkable AI, minted by `actions/create-github-app-token`. Pull requests opened that way start their workflows like any other, so `tests` and `checkable/sign-off` report on them. Without the App secrets it falls back to `GITHUB_TOKEN`, and GitHub then starts no workflow on those pull requests.
5. It posts the gate comment and sets `checkable/sign-off` to red on each new pull request, then a separate job assumes the email role through OIDC and sends one email per new pull request or version update.

The job summary has one row per reaching change: version, vendor date, the tools it reaches and what the run did. A change that has ended, such as the court preservation order that reached ChatGPT Plus, opens no pull request. The gate lists it for the record.

### Flow 2: the pull request gate

`checkable-gate.yml` runs when a pull request to `main` opens, and `checkable-sign-off.yml` runs the same check on every later commit, reopen and label change. The opening run skips pull requests that only add `changes/**`, because the nightly check posts the gate comment on those itself.

1. The gate code and the feed come from the base commit. The pull request's files are read through the GitHub API, so nothing from the pull request runs.
2. It diffs the register by tool id. Added, changed and removed tools each get a section in one sticky comment, with the vendor terms links, the AU, EU and US rules and one line each on why they reach a business on that plan, and every open vendor change affecting it.
3. It reads every changed `service/**/model.yaml` and every changed YAML file under `k8s/`. A model config, or a Kubernetes resource that declares an AI vendor, plan or model, is matched to the register by plan id, or by vendor and product when it names no plan. It gets the same terms, rules and open changes. A plan the register does not list blocks sign-off until the same pull request adds it to the register.
4. The check goes red when any tool, model config, Kubernetes AI declaration or change record moved, or when the pull request changes the gate's own files (`feed-snapshot/`, `scripts/`, `templates/`, `tests/` or `.github/`). A pull request that touches none of these goes green straight away with "No AI tools changed".
5. A person with write access adds the `checkable-signed-off` label. The gate records the sign-off against that exact commit and turns the check green. Any new commit clears it. Pull requests from forks stay red, because the sign-off has to come from inside the repository.

The job summary gives the result and one row per changed tool or config, with its plan, its register entry and the number of open vendor changes on it.

Kubernetes manifests declare AI model use with these annotations on the resource or its pod template, or the same names as container env entries or ConfigMap keys:

| Annotation | Env or ConfigMap key |
|---|---|
| `checkable.ai/vendor` | `CHECKABLE_AI_VENDOR` |
| `checkable.ai/product` | `CHECKABLE_AI_PRODUCT` |
| `checkable.ai/plan` | `CHECKABLE_AI_PLAN` |
| `checkable.ai/model` | `CHECKABLE_AI_MODEL` |
| `checkable.ai/register-tool` | `CHECKABLE_AI_REGISTER_TOOL` |

### The summariser service

`service/summariser/` is a dummy internal service, a Python 3.12 AWS Lambda handler with two routes. `GET /health` returns the configured model. `POST /summarise` with `{"text": "..."}` returns a placeholder summary with the vendor, plan and model from `service/summariser/model.yaml`. It never calls an AI vendor. `model.yaml` names the register entry `gemini-api-paid`, so a developer pull request that switches it to another vendor plan shows the gate at work. `docs/demo-script.md` walks through that switch.

## Install in your repository

1. Copy `.github/workflows/checkable-nightly.yml`, `checkable-gate.yml`, `checkable-sign-off.yml` and `tests.yml`, `.github/CODEOWNERS`, and the `scripts/`, `templates/` and `feed-snapshot/` folders into your repository.
2. Add your register as `ai-vendor-register.yaml` at the root, one entry per AI tool with the `plan` id the feed uses, and an empty `changes/` folder holding a `.gitkeep` file. Put your organisation's name in `organisation` and set `fictional: false`, or delete that line. The pull requests, change records, emails and gate comment take the name from the register.
3. Point each service's AI config at a register entry, in a flat `service/<name>/model.yaml` (`vendor`, `product`, `plan`, `model`, `register_tool`) or with the Kubernetes annotations above.
4. Create a GitHub App owned by your organisation, with repository permissions Contents, Pull requests and Issues set to read and write. Install it on the repository. Store its App ID as the secret `CHECKABLE_APP_ID` and a private key as `CHECKABLE_APP_PRIVATE_KEY`. The token action warns that `app-id` is deprecated in favour of `client-id`. Both work today.
5. In Settings, Actions, General, keep the default workflow permissions at read. If you skip the App, also tick "Allow GitHub Actions to create and approve pull requests".
6. Create the two labels, or let the first run create them:
   ```sh
   gh label create ai-governance --color 0e8a16 --description "A vendor change from the Checkable feed"
   gh label create checkable-signed-off --color 1d76db --description "A person read the Checkable gate comment and signed this off"
   ```
7. Set the repository variable `FEED_URL` to the feed address Checkable AI gives you. Until it is set, both checks read `feed-snapshot/changes.json`.
8. Email is optional and runs in your own AWS account. Add the GitHub OIDC provider (`token.actions.githubusercontent.com`, audience `sts.amazonaws.com`) and a role whose trust policy accepts only the `sub` claim `repo:<owner>/<repo>:ref:refs/heads/main`. Give the role this policy and nothing else, with your own region, account, SES identity, sender and recipients:
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
9. Add a branch ruleset for `main` that requires a pull request, code owner review and the status checks below.

Tell us what you have, and we'll help with the rest, through the enquiry form at https://checkableai.com/.

## Required checks

| Check | Published by | Kind |
|---|---|---|
| `tests` | `tests.yml`, job `tests` | Check run |
| `checkable/sign-off` | `checkable-gate.yml` and `checkable-sign-off.yml` (and the nightly check on its own pull requests) | Commit status |
| `terraform/plan` | `deploy.yml` (flow 3) | Check run |
| `k8s/policy` | the Kubernetes policy workflow (flow 4) | Check run |

A required check has to report on every pull request, or the pull request waits for it forever. `tests` and `checkable/sign-off` run with no path filter for that reason, and the flow 3 and 4 checks follow the same rule. Add `terraform/plan` and `k8s/policy` to the ruleset in the same change that adds their workflows.

The gate and sign-off workflows also publish their job check runs, `gate` and `sign-off`. These end green once the status is posted, so the `checkable/sign-off` status is the one result to read.

## Settings

| Setting | Purpose |
|---|---|
| `CHECKABLE_APP_ID`, `CHECKABLE_APP_PRIVATE_KEY` (secrets) | The org GitHub App the nightly check opens pull requests with. Unset, it falls back to `GITHUB_TOKEN`. |
| `FEED_URL` | The feed file on checkableai.com. Unset, the Actions read the snapshot in this repository. |
| `ALERT_TO` | Where the alert email goes. `hello+feed-test@checkableai.com` when unset. In this demo the role accepts that address and `hello+feed-demo@checkableai.com`. |
| `ALERT_FROM` | `feed@checkableai.com` when unset, the only sender the demo role accepts. |
| `AWS_ROLE_ARN` (secret) | The role the alert job assumes through OIDC. In `checkable-ai/ci-demo` it defaults to `arn:aws:iam::726495711127:role/checkable-ci-demo-ses`. A copy of the repository sends nothing until it sets its own. |
| `AWS_REGION` | The SES region, `ap-southeast-2` when unset. |
| `CHECKABLE_BOT_LOGINS` | Optional. The App's bot login, for example `checkable-ai[bot]`, if it ever posts the gate comment. |

GitHub pauses scheduled workflows in a repository that has had no commit for 60 days. A monthly refresh of `feed-snapshot/changes.json` keeps the nightly check running and keeps the snapshot current.

## Try it

Follow `docs/demo-script.md`. It runs the nightly check, adds Claude Pro to the register and switches the summariser from the Gemini API paid tier to the OpenAI API platform, with what each step shows.

Unit tests under `tests/` cover the Action code, every template and the summariser. Run them with `pip install -r scripts/requirements-dev.txt` and `python -m pytest`.

## What is in the feed

`feed-snapshot/changes.json` is a copy of the Checkable demo feed, validated by `feed-snapshot/changes.schema.json`. It carries a short catalogue of plans, each with vendor terms links and the AU, EU and US rule codes from our knowledge bases, and the latest version of each vendor change with its evidence. A quote appears only where the source page's licence allows it, and the licence is named on every quote. Where it does not, the entry carries Checkable AI's reading in our words and the link to the source.

The rules per plan and every reading are Checkable AI's reading, not legal advice. Confirm them with your adviser.

Copyright Checkable AI. All rights reserved. Vendor quotes stay under their own licence, named on each quote.
