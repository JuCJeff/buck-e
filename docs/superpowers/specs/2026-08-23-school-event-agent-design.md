# School Event Agent — Design Spec

**Date:** 2026-08-23
**Hackathon:** All Things Agentic Hackathon — Collaborative Partner track
**Deadline:** 2026-08-31 (≈8 days from design time — MVP-first, see cut line)

## Problem

A student's inbox gets emails from school addresses announcing real-life events
(info sessions, club meetings, hackathons, etc.), mixed in with everything else.
Manually spotting these, deciding whether to go, and signing up is friction. This
project automates the pipeline from "email arrives" to "added to my calendar,"
while keeping a human in the loop specifically at RSVP time, where the agent
asks only the questions it doesn't already know the answer to and remembers the
answers for next time — this is the "collaborative partner" behavior the track
judges on.

## Required constraints (hackathon rules, non-negotiable)

- Must use Gemini (3.5+) via Gemini API or Vertex AI.
- Must use a Google agent framework — this project uses **Google ADK**.
- Must use at least one GCP infra service — this project uses **Pub/Sub**
  (Gmail push ingestion) and **Firestore** (data store).
- Deploy target: **Cloud Run** (backend) — demo video must show the backend
  running on Google Cloud.
- Deliverables at submission: hosted URL (encouraged), repo URL, README setup
  instructions, architecture diagram, ~4 min demo video, text description.

## Architecture

```
Gmail (student's inbox)
   │  watch() push
   ▼
Cloud Pub/Sub topic ──push──▶ POST /webhooks/gmail  ┐
                                                      │  Cloud Run (FastAPI)
Google Forms API (read struct) ◀────────────────────┤
Gemini API (Vertex/API) ◀───────────────────────────┤
Google Calendar API ◀────────────────────────────────┤
Firestore ◀──────────────────────────────────────────┘
   ▲                                    │ GET/POST /events...
   │                                    ▼
   └──────────────────────────  Next.js frontend (Vercel)
```

### Components

**Gmail ingestion** (FastAPI on Cloud Run)
- Receives Pub/Sub push notifications (payload carries a `historyId`, not the
  message itself).
- Calls `users.history.list` since the last known `historyId`, then
  `users.messages.get` for each new message.
- Filters to messages from the school sender domain (configurable).
- Dedupes by Gmail `messageId` against a `processed_message_ids` Firestore
  collection — required because Pub/Sub retries delivery on any non-2xx
  response, and a naive handler would double-process.

**Triage + Summarizer agent** (ADK + Gemini, single LLM call)
- Classifies: is this email announcing a real-life event? (bool + confidence)
- If yes, extracts structured fields: `title`, `description`, `when`, `where`,
  `signup_type` (`none | form | reply`), `form_url` (if a Google Form link is
  present in the body).
- Fully automatic — no user-in-the-loop here. (Collaboration happens at RSVP
  time, per product decision below.)
- Low-confidence or failed extraction → event stored with `status: needs_review`
  rather than silently dropped or guessed.

**RSVP Agent** (ADK agent with tools + persistent memory — the track centerpiece)
- Triggered when the user clicks "Attend" on an event in the catalog.
- Tools: `read_form_structure` (Forms API, read-only), `get_user_profile`,
  `save_profile_field`, `build_prefill_link`, `create_calendar_event`.
- Always creates the Google Calendar event for the demo user.
- If the event has a detected Google Form: reads the form's field structure,
  diffs it against what's already known in the `user_profile` Firestore doc,
  and asks the user (via the frontend) only the fields it doesn't already know
  — not the ones it can already fill in. New answers are saved back to
  `user_profile` so future events don't re-ask the same personal-info
  questions (name, email, dietary preference, etc.), only event-specific ones.
- Ends by returning a **Google Forms prefilled link** (official, documented
  mechanism) for the user to do one final confirming click — no unofficial
  form-submission POST is used, since Google's Forms API has no supported
  submit-on-behalf-of-user endpoint.

**Frontend (Next.js on Vercel)**
- Catalog page: event cards from `GET /events`, filterable by status
  (`new | needs_review | attending | declined`).
- "Attend" action: if the RSVP agent has clarifying questions, opens a small
  Q&A panel; otherwise goes straight to confirmation.
- Confirmation view: shows "added to calendar" state plus the prefilled-form
  link when applicable.

## Data model (Firestore)

- `events/{id}`: `subject`, `sender`, `receivedAt`, `title`, `description`,
  `when`, `where`, `signup_type`, `form_url`, `status`, `calendarEventId`
- `processed_message_ids/{gmailMessageId}`: dedupe guard, no other fields needed
- `user_profile` (single doc — single demo user, see scope decision below):
  accumulated known answers (name, email, dietary preference, etc.) the RSVP
  agent has learned across events

## Scope decisions (from brainstorming Q&A)

These were explicitly chosen to keep the build achievable in ~8 days — noted
here so they aren't re-litigated during implementation:

1. **Collaboration point:** clarifying Q&A happens at RSVP time only, not at
   triage. Triage is a fully automatic classifier.
2. **Agent framework:** Google ADK (not raw GenAI SDK or GenKit).
3. **Gmail ingestion:** real Pub/Sub push (not polling) — this is also the
   project's GCP infra requirement alongside Firestore.
4. **Signup automation:** narrow case — Google Form embedded in the event
   email. Not a generic browser-automation/arbitrary-form-filler.
5. **Form submission mechanism:** prefilled link + one user click, not a
   simulated POST to the form's unofficial response endpoint. Slightly less
   "autonomous" but zero unofficial-API risk for a live demo.
6. **User/auth model:** single hardcoded demo user (your own Google account),
   OAuth'd once server-side for Gmail/Calendar/Forms scopes. No frontend login
   flow, no multi-user token storage.
7. **Data store:** Firestore, not SQLite/Postgres — doubles as the GCP infra
   requirement alongside Pub/Sub.
8. **Deployment:** FastAPI backend on Cloud Run; Next.js frontend on Vercel.

## Error handling

- Pub/Sub push: return non-2xx only for genuinely retryable errors (e.g.
  transient Firestore/Gemini failure); the dedupe guard makes Pub/Sub's
  automatic retries safe either way.
- Gemini classification/extraction failure: event marked `needs_review`,
  surfaced in the catalog's filter rather than dropped or blocking ingestion.
- Forms API read failure: treat the event as having no form; Calendar add
  still proceeds, RSVP falls back to "manual signup" messaging.

## Testing (lean, matched to the timeline)

- Unit tests for triage/summarizer prompt parsing, with mocked Gemini
  responses (both a clear-event and a clear-non-event case, plus a malformed
  response → `needs_review` case).
- FastAPI test-client test for webhook idempotency: same Pub/Sub push sent
  twice → exactly one `events` doc created.
- One RSVP-agent test asserting it only asks about form fields absent from
  the profile, and that answered fields get persisted to `user_profile`.
- No e2e/browser testing — explicitly out of scope for this timeline.

## MVP cut line

**Must-have (demo-blocking):**
- Gmail → Pub/Sub → triage → catalog → Attend → Calendar event created.
- RSVP agent asks only for genuinely-missing form fields and returns a
  prefilled Forms link.
- Backend deployed on Cloud Run, frontend on Vercel.

**Stretch (cut first if time runs short):**
- Demonstrating learned-profile reuse across a *second* event in the same
  demo (strong narrative beat for "adapts to the user," but not required for
  the pipeline to work).
- `needs_review` UI polish beyond a basic filter/list.
- Reply-to-RSVP-email signup path (only Google Form path is in scope).

## Open items for the implementation plan

- Exact Gemini/ADK model & prompt versions.
- Google Cloud project setup steps (OAuth consent screen, Gmail API
  domain/pubsub topic wiring, service account for Cloud Run).
- Frontend Q&A panel component design (kept minimal — no chat-framework
  dependency expected).
