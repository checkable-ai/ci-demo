A vendor change reaches the AI tools in this register, {{feed_source}} lists it, and this pull request records it. The register belongs to {{company_name}}{{#is_fictional}}, a fictional sample company, so every seat, team and number here is made up{{/is_fictional}}.

**Change.** {{title}}
**Vendor date {{vendor_date}}{{#vendor_updated}}, updated {{vendor_updated}}{{/vendor_updated}}{{#detected_on}}, detected {{detected_on}}{{/detected_on}}.**

{{summary}}

**Plans in this register**

{{#plans}}
- {{tool_name}}{{#show_plan}} ({{plan_name}}){{/show_plan}}: {{status_word}}
{{/plans}}

**What to do.** {{action}}

{{#is_replay}}
This is a replay of a real vendor change from the Checkable record, run through the register as if it had arrived today.

{{/is_replay}}
{{#has_quotes}}
**The vendor's words**

{{#quote_sources}}
{{#items}}
> {{quote}}

{{/items}}
Source: [{{source_title}}]({{source_url}}), {{source_date}}. {{credit}}

{{/quote_sources}}
{{/has_quotes}}
{{#has_readings}}
**Our reading**

{{#reading_sources}}
{{#items}}
{{our_reading}}

{{/items}}
Source: [{{source_title}}]({{source_url}}), {{source_date}}.

{{/reading_sources}}
{{/has_readings}}
**Source.** Every link above is the vendor's own page, with the date it was published. Quotes appear only where the page's licence allows them, and the licence is named on each quote. Everything else is Checkable AI's reading, in our words.

**Sign-off checklist**

- [ ] Read the vendor's note at the source link.
- [ ] Confirm which of our seats, projects or accounts it reaches.
- [ ] Carry out the action or record why not.
- [ ] Note the decision and the date in `changes/{{change_id}}.md`.
- [ ] A person signs this pull request off before it is merged, by adding the `checkable-signed-off` label.

Change `{{change_id}}`, version {{version}}. Feed {{feed_version}}, generated {{feed_generated_on}}.
{{#is_person_confirmed}}Checkable AI confirmed this entry on {{reviewed_on}}.{{/is_person_confirmed}}{{^is_person_confirmed}}AI checks it. A person signs it off.{{/is_person_confirmed}}
Opened by Checkable AI from the Checkable feed.
