# Demo script

This script runs the Checkable AI CI demo from a clean copy of `checkable-ai/ci-demo`. Every company name, seat and team in it belongs to Example Bay Advisory, a fictional sample company. The vendor changes come from `feed-snapshot/changes.json`, feed version 2026-11-06.4.

Each step names what you do, what you see and the check that shows it.

## Before you start

- The org GitHub App "Checkable AI" is installed on the repository, and the secrets `CHECKABLE_APP_ID` and `CHECKABLE_APP_PRIVATE_KEY` are set.
- The register `ai-vendor-register.yaml` is as first published: seven tools, Claude Pro not among them.
- `service/summariser/model.yaml` points at the register entry `gemini-api-paid` (vendor Google, plan `google.gemini-api.paid`, model label `gemini-flash`).

## 1. Nightly check, dry run

Open the Actions tab, pick "Checkable nightly check" and run it with `dry_run` ticked.

The job summary shows one table row for each vendor change that reaches the register:

| Change | Tool it reaches |
|---|---|
| `chg_github-2026-10-26-gpt-6-1-terra-copilot` | GitHub Copilot Business |
| `chg_google-2026-10-26-gemini-api-storage-default` | Gemini API (paid tier) |

Nothing is opened and no email is sent.

## 2. Nightly check, live

Run it again without `dry_run`.

- Two pull requests open from the Checkable AI App, each labelled `ai-governance` and adding one file, `changes/<change_id>.md`.
- On each one the `tests` check runs and passes, and `checkable/sign-off` is red with "Waiting for a person to sign off".
- The Gemini pull request quotes Google's changelog under CC BY 4.0. The Copilot pull request gives Checkable AI's reading of the GitHub blog in our words, with the link.
- One alert email per pull request arrives at `hello+feed-test@checkableai.com` (or the address in the `ALERT_TO` variable).

## 3. A developer adds a tool to the register

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

## 4. A developer switches the summariser to another vendor plan

This is the dummy switch for the summariser service. A developer moves it from the Gemini API paid tier to the OpenAI API platform, for example to compare cost and latency. Open a pull request that changes `service/summariser/model.yaml` and nothing else:

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

The check now reads "Waiting for a person to sign off". The comment shows both the new register entry and the model config matched to it. Add the `checkable-signed-off` label and the check turns green.

The same check reads Kubernetes manifests under `k8s/`. A Deployment that carries the annotation `checkable.ai/plan: openai.api.platform`, or a container env entry `CHECKABLE_AI_PLAN`, gets the same section and the same result.

## 5. A change the gate does not guard

Open a pull request that edits only `README.md`. The check is green straight away with "No AI tools changed".

## The summariser on your own machine

The service makes no AI call. It reports the configured vendor plan from `model.yaml`.

```sh
python -c "import json; from service.summariser.handler import handler; print(handler({'rawPath': '/summarise', 'requestContext': {'http': {'method': 'POST'}}, 'body': json.dumps({'text': 'The partners agreed the new fee schedule. Next steps follow.'})})['body'])"
```

The reply carries a dummy summary, `"dummy": true` and the vendor, plan and model from `model.yaml`.
