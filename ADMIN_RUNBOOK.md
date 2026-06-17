# Admin Portal — Deployment Runbook

The detailed, do-this-now checklist to turn on the admin editor. All code is already
written and in this repo — **every step below is a command you run; nothing is blocked on
anyone else.** Run everything from the repo root in PowerShell, using the same AWS CLI you
already use for `deploy.ps1`.

### Your fixed values (already filled into the commands)
| Thing | Value |
|---|---|
| Region | `us-east-1` |
| Account id | `123456789012` |
| S3 bucket | `verifyanagent-agent-sites` |
| IAM role ARN | `arn:aws:iam::123456789012:role/service-role/verifyanagent-function-role-tl3ru80t` |
| IAM role name | `verifyanagent-function-role-tl3ru80t` |
| Admin login email | `you@example.com` (hardcoded; password set at first login) |

### Prerequisites (one-time)
- AWS CLI installed and authenticated to account `123456789012`.
- `python` and `pip` on PATH (the deploy script needs them).
- The Airtable field **`verify_url_override`** (Long text) added to the `Agents` table. ✅ done.

> **Mental model:** *Save* writes to Airtable (a draft). *Publish* re-runs your **existing**
> build for that one client and uploads to S3 — live immediately (no CDN invalidation).
> The portal reuses your automation; these steps only stand up the page + endpoint + login.

---

## Phase 1 — Deploy the refactored code & smoke-test

**Why:** the admin tool required refactoring your build (the logic moved from `handler.py`
into a shared `builder.py`). This single command **rebuilds the deployment zip AND deploys
the refactored code** to your existing webhook function. It also produces `lambda_fixed.zip`,
which Phase 2 reuses. You do this **once** — it is not repeated later in the setup.

```powershell
.\deploy.ps1
```
✅ **Checkpoint:** the script prints `==> Deploy complete:` with a `LastModified` timestamp.

Now verify nothing broke by rebuilding an existing agent's site:
```powershell
.\trigger.ps1 -Email <an existing agent's email>
```
✅ **Checkpoint:** in Airtable that agent's `site_status` goes to `built`, and their live
site still looks correct. If so, the refactor is healthy — continue.

---

## Phase 2 — Create the admin Lambda

### 2a. Create the function (from the zip Phase 1 built)
```powershell
aws lambda create-function `
  --function-name verifyanagent-admin `
  --runtime python3.12 `
  --role arn:aws:iam::123456789012:role/service-role/verifyanagent-function-role-tl3ru80t `
  --handler admin_api.handler `
  --timeout 300 --memory-size 512 `
  --zip-file fileb://lambda_fixed.zip
```
✅ **Checkpoint:** the command returns JSON including `"FunctionName": "verifyanagent-admin"`
and `"State": "Active"` (or `Pending` for a few seconds).

### 2b. Set its environment variables
Get the shared secret values from your existing function:
```powershell
aws lambda get-function-configuration --function-name verifyanagent-function --query "Environment.Variables"
```
Open **`env.json`** (already in the repo, gitignored) and paste in `AIRTABLE_TOKEN`,
`AIRTABLE_BASE_ID`, and `ANTHROPIC_API_KEY`, then replace `ADMIN_SESSION_SECRET` with any
long random string you make up. (`S3_BUCKET` and `ADMIN_CORS_ORIGIN` are already filled.)

Apply it:
```powershell
aws lambda update-function-configuration --function-name verifyanagent-admin --environment file://env.json
```
✅ **Checkpoint:** the returned JSON shows your variables under `"Environment": {"Variables": …}`.

### 2c. Ensure the role can read/write S3
The admin Lambda stores your password hash at `_admin/credentials.json` and stages image
uploads under `agents/*/_uploads/`. Attach the ready-made policy (**`admin-s3-policy.json`**,
already in the repo) — it's harmless if the role already has this access:
```powershell
aws iam put-role-policy --role-name verifyanagent-function-role-tl3ru80t --policy-name admin-s3-access --policy-document file://admin-s3-policy.json
```
✅ **Checkpoint:** command returns with no error (no output is normal).

---

## Phase 3 — Give the Lambda a public URL

Two commands (this replaces API Gateway — simpler, no extra resources):
```powershell
aws lambda create-function-url-config --function-name verifyanagent-admin --auth-type NONE
```
✅ **Checkpoint & ACTION:** the output includes a **`"FunctionUrl": "https://XXXX.lambda-url.us-east-1.on.aws/"`**.
**Copy that URL** — you need it in Phase 5. (Remove the trailing slash when you use it.)

```powershell
aws lambda add-permission `
  --function-name verifyanagent-admin `
  --statement-id AdminUrlPublic `
  --action lambda:InvokeFunctionUrl `
  --principal "*" `
  --function-url-auth-type NONE
```
✅ **Checkpoint:** returns a JSON `"Statement"` string. (Without this, the URL returns 403.)

> "Public" only means *reachable*. Every action still requires your email+password, and the
> Lambda enforces CORS so only `admin.verifyanagent.com` can call it from a browser.

---

## Phase 4 — Allow browser image uploads to S3

Images upload straight from the browser to S3 (a presigned PUT), which needs a bucket CORS
rule. Apply the ready-made **`cors.json`**:
```powershell
aws s3api put-bucket-cors --bucket verifyanagent-agent-sites --cors-configuration file://cors.json
```
✅ **Checkpoint:** no error. Verify with:
```powershell
aws s3api get-bucket-cors --bucket verifyanagent-agent-sites
```
(should echo the `PUT` rule for `https://admin.verifyanagent.com`).

---

## Phase 5 — Publish the admin page

### 5a. Point the page at your Lambda URL
Edit [admin/admin.js](admin/admin.js), line with `API_BASE`, and replace
`REPLACE_WITH_ADMIN_API_BASE_URL` with the **FunctionUrl** from Phase 3 (no trailing slash),
e.g.:
```js
const API_BASE = localStorage.getItem('apiBase') || 'https://XXXX.lambda-url.us-east-1.on.aws';
```

### 5b. Upload the page
It serves at `admin.verifyanagent.com` automatically (your edge router maps any subdomain to
`agents/{name}`), so it just needs to live at the `agents/admin/` prefix:
```powershell
aws s3 sync admin "s3://verifyanagent-agent-sites/agents/admin"
```
✅ **Checkpoint:** the sync lists `upload:` lines for `index.html`, `admin.js`, `admin.css`.

> Do **not** create a real agent named "Admin" — its slug would collide with `agents/admin`.

---

## Phase 6 — First sign-in & end-to-end test

1. Open **https://admin.verifyanagent.com**. You should see **"Set your admin password"**
   (because no password exists yet). Set one — it's stored as a salted hash in S3.
2. You land on the client list. Open any client.
3. Edit a simple field (e.g. Bio) → **Save** → you'll see an "unpublished changes" banner.
4. Try the Florida case: under **Licensing**, paste an exact licensee URL into a state's
   **Custom verify link** box → **Save licensing**.
5. Click **Publish** → wait ~30–60s for "Published → https://…".
6. Hard-refresh that client's live site and confirm your edits show, including a working
   Verify button for the state you set.
7. Open **Settings** (top bar) → change your password → sign out → sign back in to confirm.

✅ If all that works, you're live.

---

## Updating things later
- **Admin Lambda code:** `.\deploy.ps1 -Function admin`
- **Admin page:** re-run `aws s3 sync admin "s3://verifyanagent-agent-sites/agents/admin"`
- **Webhook function code:** `.\deploy.ps1` (unchanged from before)
- **Your password:** Settings → Change password, in the portal.

---

## Troubleshooting
| Symptom | Likely cause / fix |
|---|---|
| Login page never loads at `admin.verifyanagent.com` | Page not synced (Phase 5b), or the slug collides with a real "Admin" agent. Confirm `agents/admin/index.html` exists in the bucket. |
| Browser console shows **CORS** error calling the Lambda | `ADMIN_CORS_ORIGIN` in `env.json` must be exactly `https://admin.verifyanagent.com`. Re-apply Phase 2b. |
| Every API call returns **403 Forbidden** | You skipped the `add-permission` command (Phase 3, 2nd command). |
| Login / Publish returns **500** with `AccessDenied` (S3) | Role lacks S3 rights — run the Phase 2c policy command. |
| Image upload fails at the "Uploading…" step | Bucket CORS missing — run Phase 4. |
| "Set password" never appears, goes straight to login | A password is already set. Use the login form, or to reset, delete `_admin/credentials.json` from the bucket and reload. |
| Publish succeeds but live site looks unchanged | Hard-refresh (Ctrl+F5). If still stale, confirm the agent's `site_status` is `built` and check `build_notes` in Airtable. |

## Route reference
| Method | Path | Purpose |
|---|---|---|
| GET | `/admin/status` | is a password set yet? |
| POST | `/admin/set-initial-password` | first-time password setup |
| POST | `/admin/login` | email + password → token |
| POST | `/admin/change-password` | change password |
| GET | `/admin/agents` | list clients |
| GET | `/admin/agents/{id}` | one client's fields + images |
| PATCH | `/admin/agents/{id}` | Save draft → Airtable |
| POST | `/admin/agents/{id}/image-url` | presigned S3 PUT |
| POST | `/admin/agents/{id}/image` | attach uploaded image |
| POST | `/admin/agents/{id}/publish` | rebuild + go live |
