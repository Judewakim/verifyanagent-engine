# Live Status feature — full brief

> Hand this to a fresh Claude Code thread. It is self-contained: it explains the
> current system, the problem, the approach, the honesty guardrails, the
> monetization design, and where every piece lives in the code.

## 1. The problem (why this exists)

Every generated agent page shows a license card per state with **Status: "Active"** —
but that value is **hardcoded in the template**, not driven by any data. It is the same
on every card for every agent, forever, regardless of whether the license is actually
active. Today this is a *latent* liability (a lapsed license still shows "Active"). In
Phase 0 we already removed the page copy that *claimed* we re-verify licenses on a
schedule and remove revoked ones, so the page is no longer self-contradictory — but the
static "Active" is the last place the page asserts something it can't guarantee.

**Goal:** make the license status reflect reality (auto-expire, self-correct), and use
that "always-true page" as the foundation for a **recurring revenue tier** (a static
snapshot isn't worth a subscription; a maintained page is).

## 2. System context (how the product works today)

Serverless, **no database — Airtable is the source of truth.**

- **Airtable** `Agents` table = all agent data (via `airtable_client.py`).
- **S3** bucket `verifyanagent-agent-sites`, each site at `agents/{slug}/`. Uncached
  origin, so an upload is instantly live. An edge router maps `{slug}.verifyanagent.com`.
- **Two Lambdas, one shared build module:**
  - `handler.py` — Stripe webhook (`checkout.session.completed`) → calls `builder.build_site`.
  - `admin_api.py` — admin CMS API + public signup API. `/publish` also calls `builder.build_site`.
  - `builder.py` — the shared pipeline: mark paid → upload assets → **OCR certs** → build
    per-state card data → render → upload → write status/notes back to Airtable.
- **`cert_ocr.py`** — Claude Haiku 4.5 vision reads each cert PDF.
- **`state_data.py`** — 50 states + DC: name, dept, seal filename, and a verify-URL template.
- **`site_generator.py`** — Jinja render + brand-color contrast.
- **`templates/index.html.j2`** — the delivered page. NOTE: `deploy.ps1` copies `templates/`
  → `package/templates/` at build time, so edit the source in `templates/`, not `package/`.

### Where status lives now
- `templates/index.html.j2`, license-card loop: the status row is hardcoded
  `<span class="lic-value lic-active">Active</span>`. License Type is also hardcoded
  "Life & Health". Neither is data-driven.
- Per-state card dicts are built in `state_data.build_states_for_agent(...)` and consumed
  by the `{% for state in states %}` loop in the template.

### The OCR schema (what we already extract)
`cert_ocr.py` → `CertExtraction` (pydantic):
- `license_number: Optional[str]`
- `confidence: "high" | "medium" | "low"`
- `name_on_cert: Optional[str]`
- `name_matches: Optional[bool]`

`extract_cert(pdf_bytes, state_abbrev, state_name, agent_name)` runs `claude-haiku-4-5`
vision with `output_format=CertExtraction`. Cost is a few cents per agent. This is the
natural place to also read the **expiration date**.

## 3. The approach (recommended build)

**Step A — OCR the expiration date.**
Add `expiration_date: Optional[str]` (ISO `YYYY-MM-DD`) to `CertExtraction` and one line to
the prompt in `cert_ocr.py`. Handle gracefully: many certs don't print an expiration, and
some states issue perpetual/continuous licenses — return `null` in those cases.

**Step B — Store it.** Add a per-state expiration to the Airtable record (mirror how
`license_numbers_override` / cert data is stored). Thread it through `builder.py` and
`state_data.build_states_for_agent` into the per-state card dict.

**Step C — Derive status instead of hardcoding.** In the card dict, compute a status from
the expiration date and render it in the template:
- has date, in the future → **"Valid through MM/YYYY"**
- has date, past → **"Expired"** (distinct styling)
- no date → fall back to a neutral label (e.g. **"Licensed"**), never a false "Active".

**Step D — Scheduled re-check + republish.** New Lambda on an EventBridge cron (daily):
scan Airtable records, flip any state past its expiration, and **republish affected pages
by calling `builder.build_site`** (or a lighter re-render path). Because the S3 origin is
uncached, the corrected page is live immediately.

**Step E — Notify.** Send the agent an email (AWS SES) N days before a cert expires, and
when a page flips to Expired.

## 4. Honesty guardrails (do NOT recreate the original problem)

- **Expiration ≠ current validity.** A license can be revoked/suspended *before* it
  expires, or renewed *after*. So present it as document-sourced: "Valid through {date}
  (per certificate on file)" — **never** "verified active in real time."
- Not every cert has a date; some states are perpetual. Handle the null case honestly.
- This is a **step toward** real re-verification (periodic NIPR/DOI checks), not equal to
  it. Don't let marketing copy outrun what the code does — that's exactly what Phase 0 fixed.
- Current honest modal copy already reflects "drawn from official records and documents."
  If you later add *real* regulator re-checks, you can strengthen the claims again — but
  only then.

## 5. Monetization / product design (open questions to decide)

This feature is the basis for a recurring tier. Decisions needed before it's a paid product:
1. **Notification value.** The state already emails the agent about renewal, so a bare
   "your cert expires soon" reminder is thin. The real recurring value is *the public page
   stays accurate on its own*. Consider bundling: consolidated multi-state renewal calendar,
   CE-deadline tracking.
2. **Renewal assist.** Deep-link each state's renewal portal? A concierge touch? Define the
   actual help vs. just a link.
3. **Self-serve updates.** An authed agent portal to re-upload a renewed cert so the page
   updates automatically (today updates go through the admin/owner). This is the most
   recurring-worthy convenience.
4. **What justifies recurring, and cadence.** Likely: accurate self-maintaining page +
   auto-update on renewal + renewal/CE assistance + hosting. Monthly is a hard sell for this
   alone; a modest **annual** "keep-it-live" fee is more defensible. Decide the bundle first,
   price second.
5. **Checkout presentation.** Base $300 (snapshot) + optional "Keep it Live" annual add-on,
   OR two named tiers (Verified Snapshot vs Verified Live). Requires a Stripe **subscription**
   (today it's a one-time Payment Link) and copy that doesn't undercut the base product.

## 6. Files / dependencies
`cert_ocr.py` (schema + prompt), `state_data.py` (`build_states_for_agent`, status derivation),
`builder.py` (thread expiration through), `site_generator.py`, `templates/index.html.j2`
(status render + styling), `admin_api.py` (expose/edit expiration in the CMS),
`apex_site/signup.html` (optionally collect expiration), a **new scheduled Lambda** (EventBridge),
**AWS SES** (notifications), **Airtable schema** (expiration fields), **Stripe subscription**
(recurring tier). Remember `deploy.ps1` mirrors `templates/` → `package/templates/`.

## 7. Rough effort
- OCR expiration field + status derivation + template render: **hours.**
- Scheduled sweep Lambda + SES notifications: **~1–2 days.**
- Self-serve agent update portal: **larger** (new authenticated surface).
- Recurring billing (Stripe subscription + checkout presentation): **moderate.**

## 8. Suggested sequence
1. OCR expiration + derive status + render (ships an honest, self-correcting page in the base product).
2. Scheduled sweep + expiry notifications.
3. Decide the recurring bundle (Section 5) → build self-serve updates → Stripe subscription → launch tier.
