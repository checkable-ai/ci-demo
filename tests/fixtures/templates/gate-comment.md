{{gate_marker}}
Stand-in gate comment for tests. {{company_name}}, {{repo}}, PR {{pr_number}}, head {{head_sha_short}}, {{feed_source}}, feed {{feed_version}}, {{register_path}}, {{operates_in}}.
{{#nothing_to_check}}
No AI tools changed.
{{/nothing_to_check}}
{{#tools}}
- {{change_kind}} {{tool_name}} {{plan_id}} {{plan_name}} {{vendor_name}}
{{^in_catalogue}}
  Not in the catalogue.
{{/in_catalogue}}
{{#terms}}
  Terms: {{title}} {{url}}
{{/terms}}
{{#rules_au}}
  AU {{code}} {{name}} {{why}}
{{/rules_au}}
{{#rules_eu}}
  EU {{code}} {{name}} {{why}}
{{/rules_eu}}
{{#rules_us}}
  US {{code}} {{name}} {{why}}
{{/rules_us}}
{{#open_changes}}
  Open: {{change_id}} {{title}} {{status_word}} {{action}} {{source_url}} v{{version}}
{{/open_changes}}
{{/tools}}
{{#removed_tools}}
Removed {{tool_name}}
{{/removed_tools}}
{{#change_records}}
Record {{change_id}} {{title}}
{{/change_records}}
{{#signed_off}}
Signed off by {{signed_by}} on {{signed_on}} at {{signed_sha_short}}.
{{/signed_off}}
{{#needs_sign_off}}
Add the label {{label_name}}.
{{/needs_sign_off}}
{{#sign_off_cleared}}
A new commit cleared the sign-off.
{{/sign_off_cleared}}
{{#is_fork}}
Fork.
{{/is_fork}}
{{#register_error}}
Register error {{register_error}}
{{/register_error}}
{{#sign_off_denied}}
The label was removed. Denied {{denied_login}}
{{/sign_off_denied}}
