---
change_id: chg_google-2026-10-26-gemini-api-storage-default
event_id: evt_01M5XZ3NH82AB7WHQP2FE2SMKG
version: 1
vendor_date: 2026-10-26
feed_version: 2026-11-06.4
tools: [gemini-api-paid]
status: awaiting sign-off
---
# Google turns request storage on by default for new Gemini API paid projects

Google, Gemini API. Vendor date 26 Oct 2026, detected 26 Oct 2026. Recorded from the feed snapshot in this repo (feed-snapshot/changes.json), feed 2026-11-06.4.

This record belongs to the AI vendor register of Example Bay Advisory, a fictional sample company.

## What changed

Google's Gemini API changelog of 26 Oct 2026 says new projects using the Generate Content API on the paid tier now store requests by default (store=true). Existing projects keep their current setting. The note does not mention the free tier.

## Who it reaches

- Gemini API (paid tier): Reaches you

## What to do

Check any Gemini API project created from 26 Oct 2026. Set store=false per request or turn off Generate Content API logging in the Logs and Datasets settings if you do not want requests kept.

## The vendor's words

> New projects using the Generate Content API (generateContent, streamGenerateContent, and batchGenerateContent) on the paid tier now store requests by default (store=true), matching the Interactions API.

> Existing projects keep their current setting. To opt out, set store=false on individual requests or turn off Generate Content API logging in the Settings panel of the Logs and Datasets dashboard.

Source: Gemini API changelog, https://ai.google.dev/gemini-api/docs/changelog, 26 Oct 2026. Google for Developers, licensed under CC BY 4.0 (https://creativecommons.org/licenses/by/4.0/).

## Decision

Date:
Decided by:
Seats, projects or accounts it reaches:
Action taken, or why not:

## Record

Change `chg_google-2026-10-26-gemini-api-storage-default`, version 1. Feed 2026-11-06.4, generated 6 Nov 2026.
AI checks it. A person signs it off.
