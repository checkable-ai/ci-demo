{{gate_marker}}
**Checkable gate for pull request #{{pr_number}}**, commit `{{head_sha_short}}`, checked against {{feed_source}} (feed {{feed_version}}). Register: `{{register_path}}` of {{company_name}}{{#is_fictional}}, a fictional sample company{{/is_fictional}}{{^is_fictional}},{{/is_fictional}} operating in {{operates_in}}.

{{#nothing_to_check}}
**No AI tools changed.** This pull request leaves `{{register_path}}`, the AI model configs under `service/` and `k8s/`, the change records and the gate files alone, so the `checkable/sign-off` check is green with nothing to sign.
{{/nothing_to_check}}
{{^nothing_to_check}}
{{#has_unregistered}}
**A service uses an AI plan the register does not list.** Add the tool to `{{register_path}}` in this pull request. The label cannot turn this check green until the register lists it.

{{/has_unregistered}}
{{#has_service_errors}}
**A service AI config does not parse.** Fix it first. The label cannot turn this check green while it does not parse.

{{#service_errors}}
- `{{path}}`: {{error}}
{{/service_errors}}

{{/has_service_errors}}
{{#has_gate_files}}
**Gate files changed. A person signs this off.** This pull request changes files the Checkable gate runs from or checks against. The gate always runs from the base commit, so these changes take effect only after merge, and a person reads them before sign-off.

{{#gate_files}}
- `{{path}}`
{{/gate_files}}

{{/has_gate_files}}
{{#tools}}
### {{tool_name}} ({{change_kind}})

{{#is_service}}
AI model config.{{#has_before}} Before: {{before}}.{{/has_before}} Now: {{after}}.

{{#in_register}}
Register entry: {{register_tool}}.
{{/in_register}}
{{^in_register}}
**Not in the register.** No tool in `{{register_path}}` is on {{after_plan}}. Add it to the register in this pull request.
{{/in_register}}
{{#register_note}}

{{register_note}}
{{/register_note}}

{{/is_service}}
{{#in_catalogue}}
Plan `{{plan_id}}`, {{plan_name}} from {{vendor_name}}. In the Checkable catalogue.

**Vendor terms**

{{#terms}}
- [{{title}}]({{url}})
{{/terms}}

**Rules that reach a business using this plan**, Checkable AI's reading. Not legal advice, confirm with your adviser.

AU
{{#rules_au}}
- {{code}}, {{name}}. {{why}}
{{/rules_au}}

EU
{{#rules_eu}}
- {{code}}, {{name}}. {{why}}
{{/rules_eu}}

US
{{#rules_us}}
- {{code}}, {{name}}. {{why}}
{{/rules_us}}

{{#has_open_changes}}
**Open vendor changes affecting this plan**

{{#open_changes}}
- `{{change_id}}` (version {{version}}): {{title}}. {{status_word}}. What to do: {{action}} Source: {{source_url}}
{{/open_changes}}
{{/has_open_changes}}
{{^has_open_changes}}
**Open vendor changes affecting this plan.** None in the feed as at feed {{feed_version}}.
{{/has_open_changes}}
{{#has_ended_changes}}

**Ended vendor changes, for the record.** These reached this plan and have since ended, so they need no action now. They stay listed so the register shows when the plan was exposed.

{{#ended_changes}}
- `{{change_id}}` (version {{version}}): {{title}}. Source: {{source_url}}
{{/ended_changes}}
{{/has_ended_changes}}
{{/in_catalogue}}
{{^in_catalogue}}
Not in the Checkable catalogue. The feed carries no terms, rules or vendor changes for this tool, so a person reads the vendor's terms before sign-off and records what they found in this pull request.
{{/in_catalogue}}

{{/tools}}
{{#removed_tools}}
- Removed from the register: {{tool_name}}. Confirm the seats are closed and any data export or deletion is done before sign-off.
{{/removed_tools}}
{{#removed_services}}
- AI model config removed: `{{source_path}}` no longer declares {{before}}. Confirm the service has stopped using it before sign-off.
{{/removed_services}}
{{#change_records}}
- Change record `changes/{{change_id}}.md`: {{title}}. A person reads the vendor's words or our reading and the action before sign-off.
{{/change_records}}

{{#is_fork}}
**Sign-off is not available on a pull request from a fork.** The check stays red. A maintainer brings the change onto a branch in this repository, where a person can sign it off.
{{/is_fork}}
{{^is_fork}}
{{#signed_off}}
**Signed off** by {{signed_by}} on {{signed_on}} at commit `{{signed_sha_short}}`. The `checkable/sign-off` check is green. A new commit clears this sign-off, and the label is then needed again.
{{/signed_off}}
{{^signed_off}}
{{#needs_sign_off}}
{{#sign_off_cleared}}
**A new commit cleared the earlier sign-off.** The check is red again until a person reads this comment against commit `{{head_sha_short}}` and adds the `{{label_name}}` label.
{{/sign_off_cleared}}
{{#sign_off_blocked}}
**Sign-off is blocked.** Fix the service AI config above first, or add its tool to `{{register_path}}`. Then someone with write, maintain or admin permission on this repository reads this comment and adds the `{{label_name}}` label against the new commit.
{{/sign_off_blocked}}
{{^sign_off_blocked}}
{{^sign_off_cleared}}
**Waiting for a person to sign off.** The `checkable/sign-off` check stays red until someone with write, maintain or admin permission on this repository reads this comment and adds the `{{label_name}}` label. The sign-off is recorded against commit `{{head_sha_short}}`.
{{/sign_off_cleared}}
{{/sign_off_blocked}}
{{/needs_sign_off}}
{{/signed_off}}
{{/is_fork}}
{{/nothing_to_check}}

AI checks it. A person signs it off. Posted by Checkable AI for {{repo}}.
