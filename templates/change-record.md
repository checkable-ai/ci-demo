# {{title}}

{{vendor_name}}, {{products}}. Vendor date {{vendor_date}}{{#vendor_updated}}, updated {{vendor_updated}}{{/vendor_updated}}{{#detected_on}}, detected {{detected_on}}{{/detected_on}}. Recorded from {{feed_source}}, feed {{feed_version}}.

This record belongs to the AI vendor register of {{company_name}}{{#is_fictional}}, a fictional sample company{{/is_fictional}}.

## What changed

{{summary}}

## Who it reaches

{{#plans}}
- {{tool_name}}{{#show_plan}} ({{plan_name}}){{/show_plan}}: {{status_word}}
{{/plans}}

## What to do

{{action}}

{{#is_replay}}
This is a replay of a real vendor change from the Checkable record.
{{/is_replay}}
{{#has_quotes}}
## The vendor's words

{{#quote_sources}}
{{#items}}
> {{quote}}

{{/items}}
Source: {{source_title}}, {{source_url}}, {{source_date}}. {{credit}}

{{/quote_sources}}
{{/has_quotes}}
{{#has_readings}}
## Our reading

{{#reading_sources}}
{{#items}}
{{our_reading}}

{{/items}}
Source: {{source_title}}, {{source_url}}, {{source_date}}.

{{/reading_sources}}
{{/has_readings}}
## Decision

Date:
Decided by:
Seats, projects or accounts it reaches:
Action taken, or why not:

## Record

Change `{{change_id}}`, version {{version}}. Feed {{feed_version}}, generated {{feed_generated_on}}.
{{#is_person_confirmed}}Checkable AI confirmed this entry on {{reviewed_on}}.{{/is_person_confirmed}}{{^is_person_confirmed}}AI checks it. A person signs it off.{{/is_person_confirmed}}
