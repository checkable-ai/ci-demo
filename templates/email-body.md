{{#is_update}}The vendor has moved on a change already recorded in the AI vendor register of {{company_name}}{{#is_fictional}}, a fictional sample company{{/is_fictional}}, and {{feed_source}} now lists version {{version}}, in place of version {{previous_version}}. Checkable AI has posted the new version on pull request #{{pr_number}}.{{/is_update}}{{^is_update}}A vendor change reaches the AI tools in the register of {{company_name}}{{#is_fictional}}, a fictional sample company{{/is_fictional}}, {{feed_source}} lists it, and Checkable AI has opened pull request #{{pr_number}} to record it.{{/is_update}}

Pull request: {{pr_url}}

What changed: {{title}}
Vendor: {{vendor_name}}, {{products}}
Vendor date: {{vendor_date}}{{#vendor_updated}}, updated {{vendor_updated}}{{/vendor_updated}}{{#detected_on}}, detected {{detected_on}}{{/detected_on}}

{{summary}}

Plans in this register:
{{#plans}}
  {{tool_name}}{{#show_plan}} ({{plan_name}}){{/show_plan}}: {{status_word}}
{{/plans}}

What to do: {{action}}

{{#is_replay}}This is a replay of a real vendor change from the Checkable record.

{{/is_replay}}{{#has_quotes}}The vendor's words:
{{#quote_sources}}
{{#items}}
  "{{quote}}"
{{/items}}
  Source: {{source_title}}, {{source_url}}, {{source_date}}. {{credit}}
{{/quote_sources}}

{{/has_quotes}}{{#has_readings}}Our reading:
{{#reading_sources}}
{{#items}}
  {{our_reading}}
{{/items}}
  Source: {{source_title}}, {{source_url}}, {{source_date}}.
{{/reading_sources}}

{{/has_readings}}Next step: read the source, confirm which seats or accounts it reaches, carry out the action or record why not, then sign the pull request off with the checkable-signed-off label.

Change {{change_id}}, version {{version}}. Feed {{feed_version}}, generated {{feed_generated_on}}.
{{#is_person_confirmed}}Checkable AI confirmed this entry on {{reviewed_on}}.{{/is_person_confirmed}}{{^is_person_confirmed}}AI checks it. A person signs it off.{{/is_person_confirmed}}

Sent by Checkable AI for {{repo}}. https://checkableai.com/
