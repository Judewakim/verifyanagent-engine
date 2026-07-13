# Paid-marketing readiness — what to have before you spend

> Purpose: everything to instrument, measure, and shore up **before** putting real money
> into paid acquisition (Google/Meta/etc.). Organic ramp needs none of this and can start
> now; paid without it is spending blind. Hand this to a fresh thread when you're ready to
> build the measurement + proof layer.

## 1. The one-time-fee CAC/LTV reality (read this first)

The product is **$300 one-time**. Economics per customer:
- Revenue $300 − Stripe (~2.9% + $0.30 ≈ $9) − OCR (~$0.05) − hosting/compute (pennies)
  ≈ **~$290 gross**, received once.
- **LTV ≈ $290** today (no recurring). Referrals raise *effective* LTV if a customer brings
  others, but that's unproven.

**Why this matters for paid:** a healthy business keeps CAC well under LTV (a common target
is CAC ≤ ⅓ of LTV). With ~$290 one-time LTV, that implies a **CAC ceiling near $80–100**.
Paid audiences adjacent to insurance/financial-services are **expensive** (high CPMs/CPCs,
competitive keywords), so hitting a sub-$100 CAC on cold paid traffic is hard. **Implication:**
- Paid is unlikely to be reliably profitable on a one-time $300 product until either (a) a
  **recurring tier** raises LTV (see `live-status-feature.md`), or (b) a **referral loop**
  multiplies LTV, or (c) you find a cheap, high-intent channel.
- So the honest sequence is: **organic first** to prove conversion + build proof + referral
  loops → then test paid in *small* controlled campaigns, measuring CAC against LTV → only
  scale channels that clear the bar. Don't scale paid on faith.

## 2. Map the funnel (and where to measure)

```
Ad / post / referral
   → get-started.html (sales page)
      → /signup wizard (4 steps: details → branding → states/licensing → review)
         → Stripe payment ($300 Payment Link)
            → webhook build (builder.build_site)
               → live page {slug}.verifyanagent.com
                  → agent shares it (email sig, texts, proposals) → referrals
```
Instrument the transition at every arrow. The biggest unknowns are **visit → signup start**
and **signup start → payment** (wizard drop-off by step).

## 3. Metrics to instrument (with definitions)

| Metric | Definition | How to get it |
|---|---|---|
| Traffic by source | Sessions per channel/campaign | Web analytics + **UTM tags** on every link/ad |
| Landing conversion | % of get-started visitors who start signup | Analytics event on "Get My Page" click / step-1 load |
| Wizard completion | % who finish each of the 4 steps → payment | Step events in `signup.html` (fire on `showStep`) |
| Payment conversion | % of signup-starters who complete Stripe | Stripe + a "reached Stripe redirect" event |
| CAC | Ad spend ÷ new paying customers (per channel) | Ad platform spend ÷ attributed conversions |
| Refund/chargeback rate | Refunds + disputes ÷ sales | Stripe dashboard |
| Referral rate | New customers attributable to an existing one | Ask at signup / referral code |

## 4. Instrumentation gaps to close (current state)

- **No web analytics or conversion pixels exist** on the apex/sales/signup pages today. Add:
  - A privacy-respecting analytics tool or GA4 on `apex_site/index.html`,
    `get-started.html`, `signup.html`.
  - Meta Pixel / Google Ads conversion tag **only if** running those channels.
  - **UTM discipline** on every outbound link and ad.
- **Signup doesn't capture referral/source.** Add a hidden `source`/`utm` field to the
  `/signup` payload (`apex_site/signup.html` → `admin_api.py` `SIGNUP_FIELDS`) and store it on
  the Airtable record, and/or pass it into Stripe metadata. Without this you can't attribute
  sales to campaigns.
- **Define the "conversion" event** you'll optimize ads toward — almost certainly the Stripe
  `checkout.session.completed` (already handled in `handler.py`), fed back to the ad platform.

## 5. Thicken the proof (compounds conversion on every channel)

Current: 4 real testimonials on `get-started.html` (good — the fabricated ones are gone).
Build a system, not a one-off:
- **Automated post-purchase ask:** N days after a page goes live, email the agent for a 1-line
  quote + permission to use their name (Airtable Automation can trigger this on `site_status=built`).
- **Capture a hard number:** ask 2–3 happy agents for a concrete result (close-rate lift,
  "paid for itself in X"). One quantified case study outperforms ten vague quotes — and is the
  only honest basis for any "close more" claim.
- **Live examples / logos:** keep the "See it in the wild" circles current and add more.
- **Agent-count milestone:** a real, updatable number ("Now trusted by N agents").
- **Referral mechanics:** give each agent a referral link/code — cheapest way to raise
  effective LTV and make paid math work.

## 6. Ops readiness for volume (paid traffic stresses this)

Paid volume multiplies two things that are fine at low volume:
- **Spam:** the signup captcha (Cloudflare Turnstile) is currently **off** (only a honeypot
  guards it). Turn it on before paid — see `turnstile-setup.md`.
- **Manual review load:** the build is automatic **except** OCR misses and name mismatches,
  which need a human. Today these are written to the Airtable `build_notes` field (see
  `builder.py`: OCR-miss appends a note ~line 187, `⚠ NAME MISMATCH` ~line 174) and an
  Airtable Automation emails the operator on `built`/`error`. **IMPLEMENTED:** a dedicated
  Slack "needs review" alert now fires from `builder.build_site` (`notify.py`) whenever a build
  ends with warnings (OCR miss, name mismatch, upload failure), with a deep link straight to the
  agent in the admin editor; the admin dashboard also shows a "Needs review" badge + filter. To
  turn it on, set `SLACK_WEBHOOK_URL` on the Lambda(s) (see `ADMIN_SETUP.md`). This is the
  difference between "1-hour SLA holds at 10× volume" and "pages ship broken."

## 7. Targets to hit before scaling paid (suggested gates)
- A measured **landing → signup** and **signup → paid** rate (know your funnel).
- Refund/chargeback rate low and stable.
- A handful of quantified testimonials / at least one real case study.
- Turnstile on + OCR/name-mismatch alerting live (Section 6).
- A **small** paid test showing **CAC < ~⅓ of LTV** on at least one channel — *then* scale
  only that channel.

## 8. Bottom line
Go organic now; it needs none of the above and it *generates* the proof and referral loops
that make paid viable. Treat this document as the checklist that turns "we could run ads"
into "we can run ads profitably." The single biggest lever on paid viability is **raising LTV
(recurring tier) and/or referrals** — without that, a one-time $300 product fights an uphill
CAC battle.
