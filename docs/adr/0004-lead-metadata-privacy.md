# ADR 0004 — Privacy position for trial-lead metadata

- **Status:** Accepted, with one explicitly open question (retention)
- **Date:** 2026-07-30
- **Phase:** 1 (Trial Lead Capture)
- **Governs:** `apps/leads/models.TrialLeadProfile`, `apps/leads/attribution.py`

## Context

Spec §A.4 requires capturing, at trial registration: registration date, IP
address, device type, language, and referral/campaign source. Spec §N
constrains how: IP is personal data, needs a stated purpose, must not be
exposed beyond authorised roles, must not be sent to an external geolocation
service, and referral tracking must minimise what is stored.

These pull against each other. This ADR records where the line was drawn.

## Decision

### 1. Minimise at capture, not at display

Each captured value is reduced to the smallest form that answers the question,
**before** it is written:

| Source artefact | Stored | Discarded |
|---|---|---|
| `Referer: https://www.google.com/search?q=…&sxsrf=…` | `www.google.com` | path, query, search terms |
| `?utm_source=x&utm_campaign=y&gclid=…` | one value, ≤100 chars | everything else, including click IDs |
| `User-Agent: Mozilla/5.0 (iPhone; …)` | `mobile` | version, OS build, engine |

The discarded detail never reaches the database, so it cannot leak from it.
This is what §N means by data minimisation — not "store everything and hide
it behind a permission".

`apps/leads/attribution.py` is the only place this reduction happens, so the
policy has one implementation rather than one per caller.

### 2. IP: stated purpose, staff-only, never customer-facing

- **Purpose:** fraud and abuse triage on trial signups (the free trial is
  once-per-organisation, and a registrant creates a fresh organisation, so
  repeat-abuse detection needs *some* signal).
- **Exposure:** platform staff only. It is on `TrialLeadProfile`, whose only
  read surfaces are Django admin (staff-only) and `/api/platform-admin/`
  (`IsPlatformAdmin`). It is **not** serialised by any trial-dashboard endpoint
  or export added in this phase — the dashboard aggregates and never returns
  per-row IPs.
- **Never rendered on a customer-facing page.**

### 3. No external geolocation. Not now, not "nice to have"

§N forbids it pending policy. Independently, it would be redundant: the country
we report on is the one the registrant **selected**, which is more accurate
than an IP guess and is already a required field.

### 4. Self-referrals are dropped

Internal navigation is not acquisition data. `extract_referral_host` returns
empty when the referring host is our own, so ordinary in-site movement writes
nothing.

### 5. Attribution is first-touch, session-scoped

`remember_campaign` stores the first campaign value seen on any public page and
does not overwrite it. Rationale: the first touch is the acquisition source;
later internal navigation is not. The value lives in the existing session — no
new cookie is introduced.

**Known limitation:** attribution only survives if the visitor's first public
page view happens in the same session as registration. A visitor who arrives
via a campaign, leaves, and returns days later registers with no campaign
recorded. Fixing that needs durable cross-session identity, which is a bigger
privacy decision than this phase should make unilaterally.

## Retention — OPEN

**Current state: retained for the lifetime of the user record** (`CASCADE` on
user deletion). No expiry job exists for this data.

This is stated rather than silently assumed, because the honest answer is that
no retention policy has been set. Two reference points, neither of which fits:

- `AuditLog.retain_until` = 7 years, driven by a **regulatory** floor. That
  floor does not apply to marketing metadata, and 7 years is far longer than
  any plausible justification for keeping a signup IP.
- The GDPR-style hard-delete path (`apps/authentication/tasks.py`) prunes audit
  records, not lead profiles.

**Recommendation for the policy owner:** the IP has a short useful life —
weeks, not years — because its purpose is triaging a signup. Segmentation
fields (country, sector, employee band) have a much longer one and are not
personal data in the same way. That argues for **separating the retention of
the auto-captured block from the rest of the row** — e.g. nulling
`registered_ip` after N days while keeping the profile — rather than a single
retention period for the whole model.

That job is not implemented here: writing a deletion schedule without an agreed
policy would be inventing the policy in code, which §N and the project's
standing rule on open product decisions both forbid.

## Consequences

- A client cannot forge its own attribution: the auto-captured block is derived
  from the request inside the service and ignores any same-named POST fields.
  There is a regression test for exactly this
  (`tests/test_trial_lead_capture.py::test_client_cannot_forge_the_autocaptured_block`).
- Campaign reporting will under-count multi-session journeys. Accepted for now;
  documented above rather than hidden.
- Anyone adding a customer-facing serializer over `TrialLeadProfile` must
  exclude `registered_ip`. The field's `help_text` says so at the definition
  site so the constraint travels with the model.
