# Admin Web Editor — step-by-step setup

> ✅ **Already deployed and live** at **https://admin.verifyanagent.com** (admin Lambda
> `verifyanagent-admin` behind API Gateway `https://4qinwlny78.execute-api.us-east-1.amazonaws.com`).
> Keep this as the from-scratch rebuild reference; see [ADMIN_RUNBOOK.md](ADMIN_RUNBOOK.md)
> for the detailed checklist and troubleshooting.

One-time wiring to turn on the admin portal. The code is done; these steps just stand up
the web page + endpoint + login that let a browser reach your **existing** build. Run from
the repo root in PowerShell with the AWS CLI you already use. Region: `us-east-1`.

Your values (already filled in below): bucket `verifyanagent-agent-sites`,
account `123456789012`.

**Why any setup at all?** Publish re-uses your existing build automation as-is — it just
needs a browser-callable door, which doesn't exist yet (your current Lambda only accepts
Stripe-signed webhooks). These steps create that door; they don't rebuild anything.

Reused, so there's nothing to create: **no new domain/cert/DNS** (`admin.verifyanagent.com`
serves from `agents/admin/` automatically via your existing edge router), and **no
CloudFront invalidations**.

---

## Step 0 — Get your IAM role ARN
You already have the bucket and account id. You still need the **IAM role** (note: this is
an `…:role/…` ARN, NOT a `…:function:…` ARN):

```powershell
aws lambda get-function-configuration --function-name verifyanagent-function --query "Role" --output text
```
Call the output `<ROLE_ARN>`.

---

## Step 1 — Add the one Airtable field
In the `Agents` table add a **Long text** field named exactly **`verify_url_override`**.
This is the only new field — it stores custom per-state verify links (Florida-type states).
Every other value you edit already has its own Airtable field.

---

## Step 2 — Deploy the refactored code & smoke-test (optional but recommended)
Proves the build refactor didn't break your existing automations:

```powershell
.\deploy.ps1
.\trigger.ps1 -Email <an existing agent's email>
```
Confirm `site_status` → `built` in Airtable. This also leaves `lambda_fixed.zip` in the
repo, which the next step reuses.

---

## Step 3 — Create the admin Lambda
Same zip, same IAM role as the webhook function:

```powershell
aws lambda create-function `
  --function-name verifyanagent-admin `
  --runtime python3.12 `
  --role <ROLE_ARN> `
  --handler admin_api.handler `
  --timeout 300 --memory-size 512 `
  --zip-file fileb://lambda_fixed.zip
```

Then set its env vars. First copy the shared values from the webhook function:
```powershell
aws lambda get-function-configuration --function-name verifyanagent-function --query "Environment.Variables"
```
Create **`env.json`** (don't commit it) with those shared values plus the two admin ones
(`ADMIN_SESSION_SECRET` = any long random string you invent):

```json
{ "Variables": {
  "AIRTABLE_TOKEN": "...",
  "AIRTABLE_BASE_ID": "...",
  "S3_BUCKET": "verifyanagent-agent-sites",
  "ANTHROPIC_API_KEY": "...",
  "ADMIN_SESSION_SECRET": "<paste-a-long-random-string>",
  "ADMIN_CORS_ORIGIN": "https://admin.verifyanagent.com",
  "TURNSTILE_SECRET": "<cloudflare-turnstile-secret-key>",
  "SLACK_WEBHOOK_URL": "<slack-incoming-webhook-url>"
} }
```

**`TURNSTILE_SECRET`** is new — it's the Cloudflare Turnstile **secret** key that the public
`/signup` route uses to verify the captcha on the brand-styled signup form
(`apex_site/signup.html`; the matching **site** key is pasted into that page's `data-sitekey`).
If `TURNSTILE_SECRET` is unset, captcha verification is **skipped** (fine for local dev, not
for production).

**`SLACK_WEBHOOK_URL`** is optional — a Slack Incoming Webhook. When set, any build that ends
with warnings (OCR miss, name mismatch, upload failure) posts a "needs review" alert to Slack
with a deep link to the agent in the admin editor (`notify.py`). If unset, alerting is skipped.
Set it on the **webhook function (`verifyanagent-function`)** — that's the unattended
pay-then-build path where it matters most — and optionally on `verifyanagent-admin` too (both
run `builder.build_site`). Optional companion var `ADMIN_URL` overrides the deep-link base
(default `https://admin.verifyanagent.com`).

**CORS for the signup form:** this Lambda now serves the public signup routes too, so it must
accept requests from the apex origin. The code allows `admin.verifyanagent.com`,
`verifyanagent.com`, and `www.verifyanagent.com` **by default** (and still merges in
`ADMIN_CORS_ORIGIN` if set). To override the whole list, set `ALLOWED_ORIGINS` to a
comma-separated list of origins.

Apply it:
```powershell
aws lambda update-function-configuration --function-name verifyanagent-admin --environment file://env.json
```

**IAM check:** the role must allow `s3:GetObject`/`s3:PutObject` on the objects **and
`s3:ListBucket` on the bucket itself** (the ListBucket grant makes a missing
`_admin/credentials.json` return `NoSuchKey` → first-run setup, instead of `AccessDenied` → a
500). The ready-made [admin-s3-policy.json](admin-s3-policy.json) grants all three. It stores
your password hash at `_admin/credentials.json` and stages image uploads under
`agents/*/_uploads/`. If the role's S3 policy is scoped to `agents/*` only, add `_admin/*`.

---

## Step 4 — Give the Lambda a public endpoint (API Gateway HTTP API)
> ⚠️ **Lambda Function URLs are blocked in this account** — an anonymous (`AuthType=NONE`)
> Function URL returns `403 AccessDenied` regardless of the resource policy. Use an **API
> Gateway HTTP API** instead; it invokes the Lambda via a service principal, so it isn't
> affected. The handler already speaks API Gateway v2 (`rawPath`), so no code change is needed.

One command creates the API + `$default` route + auto-deploy stage + Lambda proxy
integration + invoke permission:
```powershell
aws apigatewayv2 create-api `
  --name verifyanagent-admin-api `
  --protocol-type HTTP `
  --target arn:aws:lambda:us-east-1:123456789012:function:verifyanagent-admin
```
It prints an **`ApiEndpoint`** like `https://abc123.execute-api.us-east-1.amazonaws.com` —
**save it for Step 6** (no trailing slash; the `$default` stage puts paths at the root, e.g.
`…/admin/status`). The portal's own email+password still guards every action, and CORS is
enforced by the Lambda to your admin origin.

If the `--target` shortcut doesn't add the invoke permission (symptom: generic `500` and the
Lambda has **no** CloudWatch log group), add it manually with the printed ApiId as `<API_ID>`:
```powershell
aws lambda add-permission --function-name verifyanagent-admin --statement-id ApiGwInvoke `
  --action lambda:InvokeFunction --principal apigateway.amazonaws.com `
  --source-arn "arn:aws:execute-api:us-east-1:123456789012:<API_ID>/*/*"
```

---

## Step 5 — Allow browser image uploads to S3
Images upload straight from the browser to S3 via a presigned PUT, which needs a bucket
CORS rule. Create **`cors.json`**:

```json
{ "CORSRules": [ {
  "AllowedOrigins": ["https://admin.verifyanagent.com"],
  "AllowedMethods": ["PUT"],
  "AllowedHeaders": ["*"],
  "MaxAgeSeconds": 3000
} ] }
```
Apply it:
```powershell
aws s3api put-bucket-cors --bucket verifyanagent-agent-sites --cors-configuration file://cors.json
```

---

## Step 6 — Publish the admin page
1. In [admin/admin.js](admin/admin.js), set `API_BASE` to the **ApiEndpoint** from Step 4
   (no trailing slash). For the live deployment it is already set to
   `https://4qinwlny78.execute-api.us-east-1.amazonaws.com`.
2. Sync the page to the `agents/admin/` prefix (served automatically at
   `admin.verifyanagent.com`):
   ```powershell
   aws s3 sync admin "s3://verifyanagent-agent-sites/agents/admin"
   ```
   (Don't name a real agent "Admin" — that slug would collide.)

---

## Step 7 — First sign-in & test
1. Open **https://admin.verifyanagent.com** → "Set your admin password" (email is fixed to
   `you@example.com`). Set it — stored in S3, changeable later under **Settings**.
2. Open a client → edit a field (try a Florida verify link) → **Save** → **Publish**.
3. Hard-refresh the client's live site and confirm the change shows.

---

## Day-to-day after setup
- **Edit the admin code later:** `.\deploy.ps1 -Function admin`
- **Edit the admin page later:** re-run `aws s3 sync admin "s3://verifyanagent-agent-sites/agents/admin"`
- **Change your password:** Settings → Change password, in the portal.

---

## Reference — routes
| Method | Path | Purpose |
|---|---|---|
| GET | `/admin/status` | is a password set yet? (drives first-run setup) |
| POST | `/admin/set-initial-password` | first-time password setup |
| POST | `/admin/login` | email + password → bearer token |
| POST | `/admin/change-password` | change password (Settings) |
| GET | `/admin/agents` | list clients |
| GET | `/admin/agents/{id}` | one client's editable fields + images |
| PATCH | `/admin/agents/{id}` | Save (draft) — writes Airtable |
| POST | `/admin/agents/{id}/image-url` | presigned S3 PUT for an image |
| POST | `/admin/agents/{id}/image` | attach the uploaded image in Airtable |
| POST | `/admin/agents/{id}/publish` | rebuild + go live (runs the existing build) |

## How it works (recap)
- **Save** writes to Airtable (the draft). Nothing live changes yet.
- **Publish** re-runs your existing build for that one client and uploads to S3 — live
  immediately (uncached origin, no CDN invalidation).
- Airtable stays the single source of truth; the portal never edits live HTML directly.
- One account, locked to `ADMIN_EMAIL` in [admin_api.py](admin_api.py). Password is a
  salted PBKDF2 hash in `_admin/credentials.json` (private S3) — never in code or env.
- **Every data field is editable**, including `name` and `npn`. Changing `name` moves the
  client to a new subdomain on publish (the editor warns you first).
