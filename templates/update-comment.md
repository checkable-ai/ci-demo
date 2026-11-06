The vendor has moved on this change, and {{feed_source}} now lists version {{version}} of `{{change_id}}`, in place of version {{previous_version}} recorded here.

**Change.** {{title}}
**Vendor date {{vendor_date}}{{#vendor_updated}}, updated {{vendor_updated}}{{/vendor_updated}}{{#detected_on}}, detected {{detected_on}}{{/detected_on}}.**

{{summary}}

**Plans in this register**

{{#plans}}
- {{tool_name}}{{#show_plan}} ({{plan_name}}){{/show_plan}}: {{status_word}}
{{/plans}}

**What to do.** {{action}}

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
Where this pull request is still open, the record file on its branch now carries version {{version}} and any earlier sign-off is cleared, so a person reads the new version and signs it off again. Where it is already merged or closed, open a fresh review of `changes/{{change_id}}.md` on `main` against the new version.

Change `{{change_id}}`, version {{version}}. Feed {{feed_version}}, generated {{feed_generated_on}}.
Posted by Checkable AI from the Checkable feed.
