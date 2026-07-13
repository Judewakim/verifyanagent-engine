# Turnstile setup — turn on signup spam protection

> Cloudflare Turnstile is a free, privacy-friendly CAPTCHA. It's wired into the code but
> currently **disabled**. This guide is the complete how-to. Hand it to a fresh thread or
> follow it yourself.

## What it protects
The public signup form (`apex_site/signup.html` → `POST /signup` in `admin_api.py`) is
unauthenticated — anyone can submit it. Today the only guard is a CSS **honeypot** field.
Turnstile adds a real bot gate. (Actual harm is bounded because a site only *builds* after
Stripe payment, but junk records and abuse still cost you noise.)

## Current state in the code (already ~90% wired)
- **Front-end (`apex_site/signup.html`):**
  - The Turnstile API script is **commented out** (~line 29).
  - The widget div exists with a placeholder: `<div class="cf-turnstile" data-sitekey="TURNSTILE_SITE_KEY_PLACEHOLDER"></div>` (~line 397).
  - `turnstileToken()` (~line 688) reads the hidden `cf-turnstile-response` input and sends it
    as `turnstileToken` in the `/signup` payload (~line 725).
- **Back-end (`admin_api.py`):** `_verify_turnstile(event, token)` (~line 508) is **already
  called** in `_signup` (~line 539). It verifies the token against Cloudflare **only if the
  `TURNSTILE_SECRET` env var is set** — otherwise it logs a warning and returns `True` (skips).
  > Note: a stale comment in `signup.html` says to "add server-side token verification" — that's
  > already done. You do NOT need to write server verification; just supply the keys.

So enabling Turnstile = **(1) get keys from Cloudflare, (2) put the site key in the page +
uncomment the script + redeploy the page, (3) set the secret key on the Lambda.** No new code.

## Step-by-step

### 1. Create the Turnstile widget (Cloudflare dashboard)
1. Sign in / create a free account at dash.cloudflare.com.
2. Go to **Turnstile** → **Add widget**.
3. Name it (e.g. "VerifyAnAgent signup").
4. **Hostnames:** add `verifyanagent.com` (and `www.verifyanagent.com` if used). The widget
   only runs on listed hostnames.
5. **Widget mode:** choose **Managed** (recommended — invisible for most users, challenge only
   when suspicious).
6. Save. Cloudflare gives you two keys:
   - **Site key** (public — goes in the HTML).
   - **Secret key** (private — goes on the Lambda).

### 2. Enable it in the signup page (`apex_site/signup.html`)
1. **Uncomment** the API script (~line 29) so it reads:
   `<script src="https://challenges.cloudflare.com/turnstile/v0/api.js" async defer></script>`
2. Replace `TURNSTILE_SITE_KEY_PLACEHOLDER` in the widget div (~line 397) with your **site key**.
3. **Redeploy** the page to the apex origin. `signup.html` is served at
   `verifyanagent.com/signup` from the **root of the `verifyanagent-agent-sites` bucket**,
   under the extension-less key `signup`:
   ```powershell
   aws s3 cp apex_site/signup.html s3://verifyanagent-agent-sites/signup --content-type "text/html; charset=utf-8"
   ```
   The origin is **uncached**, so the change is live immediately — **do not** run a CloudFront
   invalidation (not needed here).

### 3. Set the secret key on the Lambda (`verifyanagent-admin`)
`update-function-configuration` **replaces the entire environment**, so include *all* existing
vars, not just the new one:
1. Dump the current vars:
   ```powershell
   aws lambda get-function-configuration --function-name verifyanagent-admin --query "Environment.Variables"
   ```
2. Put them into `env.json` (do NOT commit it) and add/confirm `TURNSTILE_SECRET`:
   ```json
   { "Variables": {
     "AIRTABLE_TOKEN": "...",
     "AIRTABLE_BASE_ID": "...",
     "S3_BUCKET": "verifyanagent-agent-sites",
     "ANTHROPIC_API_KEY": "...",
     "ADMIN_SESSION_SECRET": "...",
     "ADMIN_CORS_ORIGIN": "https://admin.verifyanagent.com",
     "TURNSTILE_SECRET": "<your-cloudflare-secret-key>"
   } }
   ```
3. Apply:
   ```powershell
   aws lambda update-function-configuration --function-name verifyanagent-admin --environment file://env.json
   ```
Once `TURNSTILE_SECRET` is set, `_verify_turnstile` enforces automatically — a missing/invalid
token now returns `400 captcha verification failed`.

### 4. Test
- Open `verifyanagent.com/signup` — the widget should render on the review step.
- Complete a real signup — it should pass and reach Stripe.
- Cloudflare **test keys** (use in a staging copy to force outcomes):
  - Always passes → site `1x00000000000000000000AA`, secret `1x0000000000000000000000000000000AA`
  - Always blocks → site `2x00000000000000000000AB`, secret `2x0000000000000000000000000000000AA`
  - Force interactive challenge → site `3x00000000000000000000FF`
  With the always-blocks pair, a submit should be rejected with the captcha error — that
  proves server-side enforcement is on.

## Gotchas
- **Both** changes are required: the site key in the page **and** the secret on the Lambda. Set
  only one and it's either unprotected (secret missing → skipped) or broken (page missing widget).
- `update-function-configuration` overwrites the whole env block — always include existing vars.
- Hostname allowlist must contain the exact host the page is served from, or the widget errors.
- If Cloudflare is unreachable, `_verify_turnstile` returns `False` (fails closed → signup
  blocked). Acceptable, but know that a Cloudflare outage would pause new signups.
- `ADMIN_SETUP.md` documents these env vars too — keep the two in sync.

## Rollback
To disable again: re-comment the script in `signup.html` (redeploy), and/or remove
`TURNSTILE_SECRET` from the Lambda env (verification then skips). The honeypot remains either way.
