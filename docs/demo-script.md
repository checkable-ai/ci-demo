# Demo script

This script runs the Checkable AI CI demo in `checkable-ai/ci-demo`. Every company name, seat and team in it belongs to Risky Business Solutions, a fictional sample company. The vendor changes come from `feed-snapshot/changes.json`, feed version 2026-11-06.4.

Each step names what you do, what you see and the check that shows it. The first part is the scenario we record. The second part walks through the same checks from the register as first published.

## Where the repository stands

- The org GitHub App "Checkable AI" is installed on the repository, and the secrets `CHECKABLE_APP_ID` and `CHECKABLE_APP_PRIVATE_KEY` are set.
- The ruleset on `main` requires `tests`, `checkable/sign-off`, `terraform/plan` and `k8s/policy`. The `production` environment requires approval from `@checkable-ai/reviewers`.
- The nightly check has opened pull request #3 (`chg_github-2026-10-26-gpt-6-1-terra-copilot`) and pull request #4 (`chg_google-2026-10-26-gemini-api-storage-default`), both red with "Waiting for a person to sign off".
- Pull request #5 moved the summariser to the OpenAI API platform and added the tool `openai-api` to the register, which now holds seven tools. `service/summariser/model.yaml` names `openai-api`, and the Lambda function `checkable-ci-demo-summariser` runs that config in `production`.

## The recorded scenario

### A. Sign off the nightly pull request

Open pull request #4, "Google turns request storage on by default for new Gemini API paid projects", opened by `checkable-ai[bot]`.

- It adds one file, `changes/chg_google-2026-10-26-gemini-api-storage-default.md`, and carries the label `ai-governance`.
- The pull request quotes Google's changelog under CC BY 4.0, marks the Gemini API (paid tier) entry "Reaches you" and gives the action: check any Gemini API project created from 26 Oct 2026, and set `store=false` per request or turn off Generate Content API logging if you do not want requests kept.
- `checkable/sign-off` is red with "Waiting for a person to sign off". The alert email from `feed@checkableai.com` has a subject ending "(PR #4)", so it sits in its own thread.

Add the `checkable-signed-off` label as `checkable-reviewer`. The check turns green with "Signed off by checkable-reviewer". Merge it to record the change in `changes/`. It touches neither `service/` nor `infra/`, so nothing deploys.

### B. A developer moves the summariser back to the Gemini API paid tier

Open a pull request that changes `service/summariser/model.yaml` and nothing else:

```diff
 service: summariser
-register_tool: openai-api
-vendor: OpenAI
-product: openai.api
-plan: openai.api.platform
-model: gpt-mini
+register_tool: gemini-api-paid
+vendor: Google
+product: google.gemini-api
+plan: google.gemini-api.paid
+model: gemini-flash
```

What the checks show:

- `checkable/sign-off` is red with "Waiting for a person to sign off". The register already lists the plan, so a person can sign it off straight away.
- The gate comment has one section, `service/summariser/model.yaml` (changed). Before: vendor `OpenAI`, plan `openai.api.platform`, model `gpt-mini`. Now: vendor `Google`, plan `google.gemini-api.paid`, model `gemini-flash`. Register entry: `Gemini API (paid tier) (gemini-api-paid)`.
- It lists the Gemini API Additional Terms of Service and the AU, EU and US rules for the plan.
- Under open vendor changes it lists `chg_google-2026-10-26-gemini-api-storage-default` (version 1), Google turning request storage on by default for new Gemini API paid projects, marked "Reaches you", with the same action as pull request #4. This is the change the developer takes on by moving back.
- The job summary lists the config with one open vendor change and the line "Service or infrastructure files changed: `service/summariser/model.yaml`". The file deploys to production, so the sign-off is also what the deploy gate checks after merge.
- `terraform/plan` posts the plan for the new function package as a sticky comment.
- `k8s/policy` passes in seconds with "No cluster was started", because the pull request changes nothing under `k8s/` and not the register or its feed.
- `tests` passes.

The merge button stays blocked while `checkable/sign-off` is red. Add the `checkable-signed-off` label as `checkable-reviewer`. The check turns green with "Signed off by checkable-reviewer", and the pull request can merge. Push another commit and it goes red again until someone signs that commit off.

### C. Deploy

The merge starts `deploy.yml`.

1. `checkable/deploy-gate` finds the merged pull request and matches its "Signed off by checkable-reviewer" status to the sign-off recorded in the gate comment.
2. `deploy` waits for approval in the `production` environment. A member of `@checkable-ai/reviewers` approves it.
3. Terraform plans and applies the new package to `checkable-ci-demo-summariser`.
4. The smoke test calls `GET /health` and `POST /summarise` on the function URL. Both must report vendor `Google`, plan `google.gemini-api.paid` and model `gemini-flash`, read from `model.yaml`.
5. The job summary shows the URL, the model, the plan counts, the smoke test result and the pull request with its sign-off. The deployment shows under `production` in the repository's Deployments view.

## The same checks from the first-published register

These steps start from a clean copy with the register as first published: six tools, neither Claude Pro nor the OpenAI API among them, and `service/summariser/model.yaml` on `gemini-api-paid` (vendor Google, plan `google.gemini-api.paid`, model label `gemini-flash`).

### 1. Nightly check, dry run

Open the Actions tab, pick "Checkable nightly check" and run it with `dry_run` ticked.

The job summary shows one table row for each vendor change that reaches the register:

| Change | Tool it reaches |
|---|---|
| `chg_github-2026-10-26-gpt-6-1-terra-copilot` | GitHub Copilot Business |
| `chg_google-2026-10-26-gemini-api-storage-default` | Gemini API (paid tier) |

Nothing is opened and no email is sent. With `openai-api` in the register, as on `main` now, a third row appears: `chg_openai-2026-10-21-service-tier-limits` reaching OpenAI API.

### 2. Nightly check, live

Run it again without `dry_run`.

- Two pull requests open from the Checkable AI App, each labelled `ai-governance` and adding one file, `changes/<change_id>.md`.
- On each one the `tests` check runs and passes, and `checkable/sign-off` is red with "Waiting for a person to sign off".
- The Gemini pull request quotes Google's changelog under CC BY 4.0. The Copilot pull request gives Checkable AI's reading of the GitHub blog in our words, with the link.
- One alert email per pull request arrives at `hello+feed-test@checkableai.com` (or the address in the `ALERT_TO` variable). Each subject ends with its pull request number, for example "(PR #4)", so the emails do not thread together.

### 3. A developer adds a tool to the register

Open a pull request that adds Claude Pro for two partners to `ai-vendor-register.yaml`:

```yaml
  - id: claude-pro-partners
    name: Claude Pro
    vendor: Anthropic
    product: anthropic.claude
    plan: anthropic.claude.pro
    account_type: personal
    used_by: Two partners
    status: in use
```

The gate comment lists Anthropic's terms, the AU, EU and US rules for the plan and the open change `chg_anthropic-2025-08-28-consumer-terms` ("Reaches you"). The check stays red until someone with write access adds the `checkable-signed-off` label. Push another commit and it goes red again.

### 4. A developer switches the summariser to another vendor plan

This is the switch pull request #5 made. A developer moves the summariser from the Gemini API paid tier to the OpenAI API platform, for example to compare cost and latency. Open a pull request that changes `service/summariser/model.yaml` and nothing else:

```diff
 service: summariser
-register_tool: gemini-api-paid
-vendor: Google
-product: google.gemini-api
-plan: google.gemini-api.paid
-model: gemini-flash
+register_tool: openai-api
+vendor: OpenAI
+product: openai.api
+plan: openai.api.platform
+model: gpt-mini
```

What the gate shows:

- `checkable/sign-off` is red with "A service uses an AI plan the register does not list".
- The comment has a section for `service/summariser/model.yaml` with the old and new vendor, plan and model.
- It lists OpenAI's terms and the AU, EU and US rules for `openai.api.platform`.
- Under open vendor changes it lists `chg_openai-2026-10-21-service-tier-limits`, OpenAI letting API organisations restrict service tiers per project, marked "Reaches you". This is the change the developer needs to act on for the new plan.
- Under ended changes it lists `chg_openai-2025-05-13-nyt-preservation` for the record.
- A label from a writer is taken off again, because sign-off is blocked while the register does not list the plan.

Then add the tool to the register in the same pull request:

```yaml
  - id: openai-api
    name: OpenAI API
    vendor: OpenAI
    product: openai.api
    plan: openai.api.platform
    account_type: business
    used_by: Summariser service
    status: in use
```

The check now reads "Waiting for a person to sign off". The comment shows both the new register entry and the model config matched to it. Add the `checkable-signed-off` label and the check turns green. Because this pull request changes the register, `k8s/policy` starts its kind cluster and checks the manifests against the new register.

The same check reads Kubernetes manifests under `k8s/`. A Deployment that carries the annotation `checkable.ai/plan: openai.api.platform`, or a container env entry `CHECKABLE_AI_PLAN`, gets the same section and the same result.

### 5. A change the gate does not guard

Open a pull request that edits only `README.md`. The check is green straight away with "No AI tools changed".

## The summariser on your own machine

The service makes no AI call. It reports the configured vendor plan from `model.yaml`.

```sh
python -c "import json; from service.summariser.handler import handler; print(handler({'rawPath': '/summarise', 'requestContext': {'http': {'method': 'POST'}}, 'body': json.dumps({'text': 'The partners agreed the new fee schedule. Next steps follow.'})})['body'])"
```

The reply carries a dummy summary, `"dummy": true` and the vendor, plan and model from `model.yaml`.
