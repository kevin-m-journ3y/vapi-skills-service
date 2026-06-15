# SMS/MMS Site Updates — Design & Implementation Plan

> **Status:** Design (no code yet)
> **Author:** Kevin Morrell (with Claude)
> **Last updated:** 2026-06-10
> **Feature:** Let workers TEXT (and photo) their site updates instead of calling Jill.

---

## 1. Goal

Give construction workers a **text-and-photo** channel for their daily updates, as an
equal alternative to calling Jill (voice). The client wants **more detail** from the
workers filling in timesheets, and some workers respond better to typing than talking.

Hard constraints:
- **SMS + voice only.** No app, no WhatsApp.
- **QR sign-on must be preserved** — text/photo updates reinforce sign-on, not replace it.
- Must work on the **number we already have** for each tenant.
- **Per-tenant on/off** switch at super-admin level.
- Keep the client's familiar charging model (**$500 flat + ~$0.94/unit**).

---

## 2. Confirmed facts (validated, not assumed)

### Twilio setup (live API, 2026-06-10)
- Account: **Full / active**, owns both numbers.
- **BBMK** = `+61485009775` (LIVE — never test against it).
- **JOURN3Y** = `+61468086094` (test tenant — all testing here first).
- Both are **AU mobile** numbers, capabilities `sms+mms+voice`.
- **All webhooks currently point at VAPI**: `sms_url`, `voice_url`, `status_callback`
  → `api.vapi.ai/twilio/*`. Numbers are BYO-Twilio imported into VAPI.

### Pricing (this account, USD; AUD at billing FX 1.55)
| Item | USD | AUD |
|---|---|---|
| Inbound SMS | $0.0075 | ~A$0.012 |
| Outbound SMS | $0.0515 | ~A$0.080 |
| Mobile number rental | $8.25/mo | ~A$12.80/mo |
| Inbound MMS | (not yet populated; immaterial) | — |

**Outbound SMS is 7× inbound** → our replies drive cost, not workers' texts. Keep
outbound lean (batch confirmations, don't ack every message).

### MMS feasibility — CONFIRMED WORKING (live test)
Sent a photo from an AU mobile to the JOURN3Y number:
- Arrived as real **`image/jpeg`**, `num_media=1`, status `received`.
- Media downloaded with Twilio auth = valid **1.1 MB JPEG**.
- **Caveat:** the photo arrived with an **empty body** — Twilio may deliver the image
  and any caption as **separate messages**. Ingest must handle media-only messages and
  associate nearby text from the same sender.
- **Implication:** compress/downscale photos on ingest (full-res ~1.1 MB each); handle
  HEIC from other devices.

### BBMK activity baseline (last 30 days)
- 21 active users; **6 actually logging**.
- **52 timesheets**, 47 sign-ons, 25 working days.
- **43 billed calls** last month → ~50 end-of-day updates/month is the planning base.

---

## 3. Core design decisions

| # | Decision | Rationale |
|---|---|---|
| D1 | **Per-day accumulation model.** Every inbound text/photo for a worker's active sign-on appends to a running per-day log anchored to the `site_signons` row. | A day = many messages; not 1 message = 1 timesheet. |
| D2 | **Site attribution = sign-on first, ask if unsure.** Auto-attribute to the single open sign-on; ask only when 0 or multiple. | Lowest friction; reinforces QR sign-on (constraint). |
| D3 | **Text completes the timesheet.** Sign-on gives site + start; accumulated text = `work_description`; **end time captured by the SMS flow** (parse "knocked off at 3:30", else ask once). New `signoff_method = 'sms_timesheet'`. | Sign-on never sets an end time for a text-only worker → must capture it. |
| D4 | **Mid-day photo/note must NOT trigger the finish-time prompt.** Only an explicit done-signal finalizes. | Don't nag a worker dropping a lunchtime photo. |
| D5 | **Both channels always open & equivalent; workers can mix within a day.** | "Choice" = available every time, not a locked mode. |
| D6 | **Mixed-mode must not lose data.** Whichever channel finalizes aggregates the day's texts/photos into `work_description` — never overwrites. | Worker texts 3 notes then calls Jill → keep everything. |
| D7 | **Per-tenant super-admin toggle**, decoupled from the webhook (see §6). | Instant, safe on/off; no live Twilio mutation per flip. |
| D8 | **VAPI keeps voice; our app owns SMS/MMS** — same number. Repoint only the messaging webhook. | VAPI's SMS handling is too thin for the multi-turn state we need. |
| D9 | **Bill the artifact, not the call** — differentiated, per-tenant, per-type pricing; channel is a reporting tag only. | SMS adoption otherwise zeroes out call-based revenue. |

---

## 4. Conversation / flow design

### Sign-on (existing, unchanged mechanism)
Worker scans QR → `site_signons` row, `signed_on_at` set, status `active`.
**Confirmation message** now appends a channel-choice line **when inbound is enabled**:
> "You're signed onto Bondi Rd ✅. End of day: call Jill or just text this number with
> what you did — and send photos anytime. Reply STOP to mute reminders."

(Keep `post_signon_message` for tenant H&S copy; append the channel line programmatically.)

### Inbound message handling
1. **Resolve tenant** from the `To` number; if `inbound_messaging_enabled` is off → ignore
   (optional silent auto-reply).
2. **Resolve user** from the `From` number. Unregistered → reply with `manager_phone_number`.
3. **Special keywords:** `STOP` → `sms_reminders_enabled=false`; `START` → re-enable;
   `HELP`/unparseable → guidance message.
4. **Resolve site** from the open sign-on (D2): one → use it; multiple → ask; none → ask
   + nudge to scan in.
5. **Classify intent:**
   - Photo or note, no done-signal → append to day log, ack (batched). **Do not finalize.**
   - Done-signal (or finish time present) → capture end time (parse or ask once) → finalize.
6. **Finalize:** aggregate day's notes → `work_description`; hours from `signed_on_at` →
   captured end; link `timesheet_id` onto sign-on; `signoff_method='sms_timesheet'`;
   status `signed_off`. **Idempotent** — no-op if voice already closed it.
7. **Confirm:** "Saved to Bondi Rd, 7:00–15:30 ✅. Reply WRONG to fix."

### Pending-conversation state
SMS is async and multi-turn. A TTL'd store keyed by `(tenant, from_number)` remembers
"awaiting site" / "awaiting finish time", expiry ~30–60 min.

---

## 5. Data model changes

### New: pending-conversation state
`sms_pending_context(tenant_id, from_number, state, payload jsonb, expires_at)` — or an
equivalent short-lived store. One row per active conversation.

### New: message log (visibility / metering + note source + Site Log)
`message_log(id, tenant_id, user_id, signon_id, site_id, direction, channel{sms,mms},
category, from_number, to_number, body, num_segments, num_media, twilio_message_sid,
price, price_unit, status, created_at)`. Capture Twilio `price` via status callback or
delayed fetch (populates asynchronously). Inbound `body` doubles as the source for
`work_description` at finalization. **`site_id`** is stamped once the site is resolved (so
text updates with no sign-on still attribute to a site) and **`category`** classifies intent
— both added for the future **Site Log** report (see §13).

### New: media table (MMS photos)
`timesheet_media(id, tenant_id, user_id, site_id, signon_id, timesheet_id NULL,
media_url, content_type, caption, source='sms_mms', twilio_media_sid, created_at)`.
- Anchored to `signon_id` (photo arrives before the timesheet exists); `timesheet_id`
  backfilled when the day closes.
- Media stored in **Supabase Storage** (tenant-isolated bucket), compressed/HEIC-converted
  on ingest, deleted from Twilio after fetch.

### Existing tables touched
- `site_signons`: new `signoff_method='sms_timesheet'`; `signed_off_at` set on SMS finalize.
- `qr_signon_config`: new `inbound_messaging_enabled BOOLEAN DEFAULT false`.
- `tenant_billing_config`: rename `cost_per_call_*` → `cost_per_*`; add intra-day rate
  (default 0). (See §7.)

### New: "standard day" config (required by the unfinalized-day hybrid, §10)
The one-click "set to standard day" needs a default shift to suggest. Add a per-tenant
**standard-day** config (e.g. `default_start_time`, `default_end_time` or a shift-hours
value), ideally overridable per site (sites can have different standard hours). Likely lives
on `qr_signon_config` (per-tenant) and/or `entities.metadata` (per-site override). Confirm
none of this already exists before adding. Scope into **Phase 1** — the hybrid policy is
incomplete without it.

---

## 6. The per-tenant switch + webhook (operational)

**Two layers, kept decoupled:**
- **Infrastructure (one-time per number):** repoint the Twilio **Messaging** webhook from
  `api.vapi.ai/twilio/sms` → `our-app/twilio/sms/inbound`. Voice webhook untouched.
- **Runtime gate:** the super-admin toggle `inbound_messaging_enabled` in `qr_signon_config`.
  App receives all messages (webhook points to it), processes only if the tenant flag is on.

**Why decoupled:** flipping the switch is instant and safe — no live Twilio API mutation,
no VAPI re-sync fight per toggle. UI shows a read-only **"messaging route: app ✅ / VAPI ⚠️"**
indicator so a toggle that's on but not yet repointed is obvious.

**Open risk:** VAPI may overwrite a manually-changed messaging webhook. **Test on JOURN3Y
first** — repoint, send a message, confirm it sticks and lands on our endpoint.

---

## 7. Billing model

### Principle: price by artifact TYPE, not channel
A site update is worth the same spoken or typed. Channel (voice/sms) is a **reporting tag**
on the line item, never a price axis. Pricing is **differentiated per artifact type**,
**configurable per tenant**.

| Artifact type | Billable | Default | Notes |
|---|---|---|---|
| Timesheet completion | Yes | per-tenant rate | voice or text, same price |
| Voice memo / note | Yes | per-tenant rate | voice only |
| Site update / progress | Yes | per-tenant rate | voice or text |
| Intra-day update (note/photo) | Configurable | **$0** | rolls into the timesheet; standalone text = a site_update |

### Why intra-day defaults to $0
Counting each note/photo as billable recreates per-message nickel-and-diming and penalizes
the detail the client asked for. Roll intra-day media/notes into the parent timesheet's
single charge. Keep the type list small (~4) even though each rate is tunable.

### Implementation
1. `tenant_billing_config`: `cost_per_call_*` → `cost_per_*`; add intra-day rate (default 0).
2. Billing query: from "count billable **calls** by call_type" → "count billable
   **artifacts** by type" — read `timesheets` / `voice_notes` / `site_progress_updates`
   directly; derive `source` (`vapi_call_id` present → voice, else sms) for line-item display;
   roll intra-day media/notes into the parent timesheet.
3. Admin billing-config UI: expose per-type rates + new intra-day field.

### Why this is mandatory, not optional
Today billing only charges qualifying **calls**. If 100% move to SMS → **0 calls → $0 usage
revenue** while still doing the work. Per-artifact billing preserves the ~$0.94/unit revenue
channel-agnostically.

---

## 8. Cost model (BBMK, real volume)

~50 updates/month. Inbound dirt cheap; outbound dominates.

| Scenario | Updates/mo | Msgs/update (in/out) | Monthly carrier cost (AUD) |
|---|---|---|---|
| Base | 50 | 3 in / 3 out | ~A$14 |
| Busy + chatty | 75 | 5 in / 4 out | ~A$28 |
| + photo acks | 75 | +1.5 MMS in / +1.5 SMS out | ~A$37 |

Against revenue (~A$540/mo) this is **3–6%** — negligible. **No per-message customer
charge needed**; meter for visibility only. Each ~$0.94 artifact charge comfortably covers
its ~A$0.27 carrier cost.

---

## 9. Phased implementation plan

### Phase 0 — Validate webhook control (JOURN3Y only)
- Repoint JOURN3Y messaging webhook to a temporary app endpoint.
- Confirm inbound SMS lands on our endpoint and **VAPI does not re-clobber** the webhook.
- **Go/no-go for the integration approach.**

### Phase 1 — Inbound TEXT → timesheet (JOURN3Y, behind toggle)
- Inbound endpoint + Twilio signature validation.
- `inbound_messaging_enabled` flag + super-admin toggle + route indicator.
- Pending-conversation state store.
- Sign-on-first attribution; per-day accumulation; finish-time capture; finalize + idempotency.
- HELP / STOP / START handling.
- Toggle-aware reminder copy; finalization-based (not message-based) "logged" check.
- **Billing: artifact-based billing + per-type rates** (the mandatory change).
- Test end-to-end on JOURN3Y, then enable for BBMK.

### Phase 2 — MMS / photos + admin gallery
- Media pipeline: download from Twilio → Supabase Storage → compress/HEIC-convert → delete
  from Twilio.
- `timesheet_media` table; anchor to sign-on, backfill timesheet.
- Handle media-only messages + caption association.
- Admin by-site/by-day **photo gallery** in reports (the client-facing payoff); optional
  feed into Site Weekly AI report.
- `message_log` metering.

---

## 10. Decisions

### Resolved (2026-06-15)
- **Unfinalized-day policy → HYBRID.** Always create the timesheet (preserving notes/photos)
  but mark it **"needs hours"** for admin; give admin a **one-click "set to standard day"**
  that uses last-activity time as a *suggestion*. Never silently guess hours.
- **`auto_next_site` → auto-finalize prior site.** When a worker scans into a 2nd site, the
  1st sign-on auto-closes; **auto-finalize Site A's timesheet** from its accumulated notes +
  the scan-into-B time as the end time, and **re-anchor the running log to the new active
  sign-on**. Only the last site of the day needs an explicit finish. *(Accepted recommendation.)*
- **BBMK per-type rates → REVENUE-NEUTRAL at switchover.** Set timesheet + site-update to
  ~$0.94, intra-day $0, so the model change doesn't change BBMK's bill. Differentiate later
  only with a deliberate repricing conversation.
- **Photo categorization → NONE in v1.** Ship timestamped photos + caption per site/day. Add
  AI auto-tagging later only if the client wants to filter the gallery.

### Verified (2026-06-15)
- **Phase 0 — webhook repoint works; VAPI did NOT clobber it.** Live test on JOURN3Y:
  repointed `sms_url` via Twilio API → inbound SMS delivered to our URL as a standard form
  POST (`From`, `To`, `Body`, `NumMedia`, `MessageSid`, `AccountSid`, `FromCountry`); no
  immediate VAPI revert. Restored to `api.vapi.ai/twilio/sms` after. **Residual risk:** a
  VAPI background sync or a VAPI-side number operation could still revert it — when building
  Phase 1, repoint to the real endpoint, monitor for a day, and re-apply our webhook after
  any VAPI number change.

### Still to verify (not decisions)
- **Confirm inbound MMS unit price** once Twilio populates it (immaterial to the model).

---

## 11. Reused vs new

**Reused:** user-by-phone lookup, AI site matcher (`timesheet/endpoints.py:256`), overhead
detection, sign-on auto-close, `send_sms` (`app/services/twilio_service.py`),
unregistered→manager reply, existing per-tenant billing config + invoice generation.

**New:** inbound webhook + signature validation, pending-state store, per-day accumulation,
finish-time capture, MMS media pipeline + `timesheet_media`, `message_log`, admin photo
gallery, artifact-based billing refactor, super-admin toggle + route indicator.

---

## 12. Codebase grounding (verified 2026-06-15)

Direct-read confirmation of the conventions the build must follow.

### Billing (refactor surface)
- `preview_billing()` **routes.py:4228–4531**, `generate_invoice()` **4534–4694**.
- **Today bills CALLS, not artifacts.** Queries `call_quality_assessments` (≥30s, `call_type != greeter`); artifact existence (timesheets/voice_notes/site_progress_updates) is only a post-hoc **`completed` display flag**, not a billing filter (lines ~4399–4462).
- `rate_map` (lines ~4465–4469) maps `call_type` → `cost_per_call_{timesheet|voice_notes|site_updates}`; defaults 1/1/2. VAPI actual-cost fetch at **4318–4353** (keep, but make conditional on `vapi_call_id` presence).
- **Refactor:** reverse the join — query the three artifact tables directly, union with `artifact_type`, derive `channel` from `vapi_call_id` presence (present→voice, null→sms). Skill endpoints **already insert `vapi_call_id` as nullable** (timesheet/voice_notes/site_updates endpoints), so SMS artifacts insert cleanly.
- **Two watch-outs:** (a) dedup moves `vapi_call_id` → `artifact_id` (lines ~4571–4593); (b) one call can yield >1 artifact → **verify count-neutrality** at BBMK switchover (revenue-neutral decision). Add unique `(artifact_id, invoice_id)`.
- **Migration 017:** add `cost_per_intra_day_update` (default 0); add `artifact_id`, `artifact_type`, `channel` to `invoice_line_items`; make `vapi_call_id` nullable.

### Inbound webhook plumbing
- App: `app/main.py` — routers via `skill_registry.register_all_routes(app)` + `include_router(...)`. New endpoint = a **plain webhook**, not a VAPI tool.
- **Twilio webhook differs from skill pattern:** parse `await request.form()` (not JSON), return **TwiML / empty 200** (not the VAPI `{"results":[...]}` shape).
- **No Twilio signature validation exists** — net-new. Manual HMAC-SHA1 (URL + sorted POST params, keyed by auth token); no Twilio SDK in repo (httpx convention).
- DB access = inline `httpx.AsyncClient()` + PostgREST (`{SUPABASE_URL}/rest/v1/...`, service-key headers). GET/POST/PATCH. `database_rest.py` helper exists but is largely unused.
- User-by-phone lookup pattern: `app/main.py:819–856` and `authentication/endpoints.py:108–121`.

### Storage / config / sign-off
- **Voice notes store NO media** (text-only). But Supabase Storage upload pattern EXISTS: buckets `tenant-logos`, `site-note-attachments` (`POST /storage/v1/object/{bucket}/{path}`, public URL). MMS pipeline = new bucket (e.g. `mms-photos`) following that pattern.
- **No standard-day/shift-hours config exists** — net-new. Add `standard_day_start`/`standard_day_end` TIME to `qr_signon_config`; per-site override via `entities.metadata`.
- `qr_signon_config` read: `reminder_scheduler.py` (`_get_enabled_tenants`); write/upsert: `routes_qr.py:219–240`. Add `inbound_messaging_enabled` to both + the toggle UI.
- Sign-off: `auto_next_site` in `signon_service.py:record_signon` (closes active sign-ons on new QR scan; **creates no timesheet today** — the auto-finalize enhancement attaches here). `jill_timesheet` in `timesheet/endpoints.py` (~1200) sets `status=signed_off`, `signoff_method`, links `timesheet_id` — **SMS finalize mirrors this** with `signoff_method='sms_timesheet'`.
- `entities.metadata` JSONB used for `is_overhead`; same pattern for per-site standard-day override.

### Migrations
- Applied **manually via Supabase dashboard** (no runner). Current max **018**; next = **019**. Convention: `CREATE TABLE IF NOT EXISTS`, UUID PK `gen_random_uuid()`, FKs to tenants/users, TIMESTAMPTZ, indexes, RLS + service-role policy.

---

## 13. Future reports this design enables (Phase 3+)

### Site Log — per-site, scrollable daily timeline
A per-`(site, day)` **UNION** across all artifact types, each carrying `(site_id, timestamp,
type, user, content/media)`: timesheets (`work_date`), `timesheet_media` (photos),
`site_progress_updates`, `voice_notes`, `site_signons`, existing site notes, and **text
updates from `message_log`**. The 019 additions of `message_log.site_id` + `category` (and
the `(site_id, created_at)` index) make text updates first-class here — including texts that
arrived with **no sign-on** (resolved by asking), which a `signon_id`-only link would miss.
Filter `category` to show content (note/photo) vs control (help/stop).

### Text updates in the Site Weekly AI report — mostly free
Because text **completes the timesheet** (D3), accumulated text becomes the timesheet
`work_description`, which the weekly AI report already reads → **workers' text narrative is
included with no report change**. Richer intra-day detail (individual notes/photos, not just
the finalized summary) is an optional enhancement via a per-site/week query over
`message_log` + `timesheet_media`.
