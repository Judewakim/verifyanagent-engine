# verifyanagent-lambda

AWS Lambda function that automatically builds and deploys a personal license-verification website for an insurance agent the moment they pay via Stripe.

**Live sites look like:** `https://judewakim.verifyanagent.com`

---

## What This Does — End-to-End Flow

```
Agent fills Airtable form
        ↓
Agent pays on Stripe checkout
        ↓
Stripe fires a webhook → API Gateway → this Lambda
        ↓
Lambda verifies the Stripe signature (security)
        ↓
Lambda looks up the agent's Airtable form record by email
        ↓
Lambda downloads all attachments (photo, logos, cert PDFs) → uploads to S3
        ↓
Lambda builds license-card data for each state the agent is licensed in
        ↓
Lambda renders the HTML template with the agent's data
        ↓
Lambda uploads index.html + style.css + script.js to S3
        ↓
Agent's site is live at https://{slug}.verifyanagent.com
        ↓
Airtable is updated with site_status = 'built' → Automation emails Jude to review
```

If anything fails, Airtable is updated with `site_status = 'error'` and `build_notes` contains the exact error — Airtable Automation 2 emails Jude to investigate.

---

## Repository Structure

```
verifyanagent-lambda/
│
├── handler.py            ← Lambda entry point — orchestrates the whole build
├── airtable_client.py    ← All Airtable API calls
├── stripe_verifier.py    ← Validates incoming Stripe webhooks
├── s3_manager.py         ← Downloads assets from Airtable, uploads to S3
├── state_data.py         ← 50-state database + state matching + license card builder
├── site_generator.py     ← Renders the Jinja2 HTML template
├── requirements.txt      ← Python dependencies
│
├── templates/
│   ├── index.html.j2     ← The agent website HTML template (Jinja2)
│   ├── style.css         ← All styles for the agent site
│   └── script.js         ← Frontend JS (lightbox, Calendly, etc.)
│
├── package/              ← Deployment staging folder (dependencies + source + templates)
│   ├── lambda.zip        ← The zip you upload to Lambda (rebuilt each deploy)
│   └── ...               ← All pip dependencies pre-installed here
│
└── lambda/               ← Older build snapshot (reference only, not used for deploys)
```

---

## File-by-File Reference

---

### `handler.py` — Lambda Entry Point

**What it does:** The single function AWS calls (`handler(event, context)`). It is the conductor — it calls every other module in the right order and handles all error states.

**Step-by-step logic:**
1. Calls `stripe_verifier.verify()` — rejects the request immediately if it didn't come from Stripe
2. Ignores all Stripe event types except `checkout.session.completed`
3. Extracts the customer email from the Stripe payload
4. Calls `airtable_client.find_by_email()` to find the matching form submission
5. If no record found → creates an error record in Airtable and exits
6. Updates Airtable: `payment_status = 'paid'`, `site_status = 'building'`
7. Calls `s3_manager.upload_assets()` → downloads all attachments → uploads to S3
8. Calls `state_data.build_states_for_agent()` → builds license card data
9. Calls `site_generator.render()` → renders the HTML
10. Calls `s3_manager.upload_site_files()` → pushes HTML/CSS/JS to S3
11. Updates Airtable: `site_status = 'built'`, `site_url`, `build_notes`

**When to edit this file:**
- To change the overall build sequence
- To add a new top-level step (e.g. send a confirmation email via SES)
- To change what gets written to `build_notes` in Airtable
- To add a new Stripe event type you want to handle

---

### `airtable_client.py` — Airtable API

**What it does:** All communication with Airtable. Three functions:

| Function | What it does |
|---|---|
| `find_by_email(email)` | Searches the Agents table for a record matching the email. Returns the full record dict or `None`. |
| `update(record_id, fields)` | Updates any fields on an existing record. Only fields in the dict are changed. |
| `create_error_record(email, error_message)` | Creates a new Agents record flagged as an error — triggers Airtable Automation 2 to email Jude. |

**Reads from environment variables:** `AIRTABLE_TOKEN`, `AIRTABLE_BASE_ID`

**The Airtable table name** is hardcoded as `"Agents"` on line 8. Change it there if the table is ever renamed.

**When to edit this file:**
- If the Airtable table name changes
- If you need to query a different field (not email) to match agent records
- If you need to add a new Airtable API call (e.g. fetch a lookup table, create a record in a different table)

---

### `stripe_verifier.py` — Stripe Webhook Security

**What it does:** One function, `verify(event)`. Takes the raw API Gateway event and cryptographically confirms the request came from Stripe using the webhook signing secret. Raises a `ValueError` (which `handler.py` catches and returns a 400) if the signature is missing or wrong.

**Reads from environment variables:** `STRIPE_WEBHOOK_SECRET`

**When to edit this file:**
- Almost never. Only touch this if Stripe changes their webhook verification API (extremely rare).
- If you add a second Stripe account / webhook endpoint, you'd need to support multiple secrets.

---

### `s3_manager.py` — Asset Management

**What it does:** Everything related to downloading files from Airtable's CDN and uploading them to S3. Contains four functions:

| Function | What it does |
|---|---|
| `slugify(name)` | Converts `'Jude Wakim'` → `'judewakim'`. Used as the S3 folder name and subdomain. |
| `upload_assets(record, slug, errors)` | Downloads profile pic, logos, carriers image, and cert PDFs from Airtable → uploads each to `agents/{slug}/` on S3. Returns `asset_map`. |
| `upload_site_files(slug, html_content)` | Uploads the generated `index.html` string plus the bundled `style.css` and `script.js` to `agents/{slug}/` on S3. |
| `_download(url)` | Internal helper — fetches raw bytes from a URL with a 30s timeout. |

**The `asset_map` it returns looks like:**
```python
{
    'profile_pic':  'profile.jpg',
    'logo_full':    'logo-full.png',
    'logo_icon':    'logo-icon.png',    # falls back to logo_full if not uploaded
    'carriers_img': 'carriers.jpg',     # None if not uploaded
    'certs': {
        'FL': 'certs/FL.pdf',
        'TX': 'certs/TX.pdf',
    }
}
```

**Certificate PDF matching** — agents can name their cert files anything that references the state. The filename is passed to `state_data.match_state_from_filename()` (see below). Examples that all resolve to `FL`:
- `FL.pdf`, `fl.pdf`, `FL-cert.pdf`, `florida.pdf`, `florida-cert.pdf`, `floridadeptofinsurance-48945.pdf`

**Reads from environment variables:** `S3_BUCKET`

**S3 folder structure per agent:**
```
agents/jude-wakim/
    index.html
    style.css
    script.js
    profile.jpg
    logo-full.png
    logo-icon.png
    carriers.jpg
    certs/
        FL.pdf
        TX.pdf
```

**When to edit this file:**
- To add a new asset field from Airtable (e.g. a second logo variant) — add a `process_attachment()` call in `upload_assets()` and add the key to `asset_map`
- To change the S3 folder structure
- To change how `slugify()` works (e.g. include a number suffix to handle name collisions)
- The cert matching logic itself lives in `state_data.py` — edit it there

---

### `state_data.py` — State Database + Matching Logic

**What it does:** Two responsibilities — stores the static data for all 50 states, and contains the functions that use it.

#### `STATES` dictionary
Master database of all 50 US states. Each entry:
```python
"FL": {
    "name": "Florida",
    "dept": "Dept. of Financial Services",
    "seal": "florida-seal.png",       # filename in S3 assets/ folder
    "type": "license_num",            # how the verify URL is built
    "url":  "https://licenseesearch.fldfs.com/Licensee/{LICENSE_NUM}"
}
```

**`type` values and what they mean:**

| type | meaning |
|---|---|
| `"npn"` | The verify URL can be built automatically using the agent's NPN |
| `"license_num"` | The verify URL needs a state-specific license number (not NPN) — button is disabled, flagged in build_notes |
| `"manual"` | The state's portal requires filling out a form — no direct URL is possible, button is disabled |

**When to update `STATES`:**
- A state adds a new online lookup portal → change `type` to `"npn"` or `"license_num"` and add the `url`
- A state department changes its name or URL → update `dept` and/or `url`
- You upload a new seal image to S3 → update `seal`

---

#### `build_states_for_agent(selected_states, npn, cert_map, errors)`
Takes the list of state abbreviations from the agent's Airtable record (e.g. `['FL', 'TX', 'SC']`), looks each one up in `STATES`, attempts to build a verify URL, checks whether a cert was uploaded, and returns a list of dicts ready for the HTML template.

**Output (one dict per state):**
```python
{
    'name':          'Florida',
    'abbrev':        'FL',
    'dept':          'Dept. of Financial Services',
    'seal_filename': 'florida-seal.png',
    'npn':           '22168646',
    'verify_url':    'https://licenseesearch.fldfs.com/Licensee/...',  # or None
    'cert_url':      'certs/FL.pdf',   # or None if cert wasn't uploaded
}
```

---

#### `match_state_from_filename(filename)`
Maps a certificate filename to a state abbreviation. Used by `s3_manager.py` so agents don't have to name files exactly `FL.pdf`.

**3-tier matching (tried in order, first match wins):**

| Tier | Method | Example |
|---|---|---|
| 1 — Perfect | Full state name found anywhere in filename | `florida-cert-2024.pdf` → `FL` |
| 2 — Good | State abbreviation is a complete word token | `FL-cert.pdf` → `FL` |
| 3 — Good | First ≥60% of state name at start of filename | `louisian-cert.pdf` → `LA` |

Returns `None` (file is skipped) if no tier matches or if two states' abbreviations appear in the same filename.

**Key design decisions:**
- States sorted by name length descending — `westvirginia` matches WV before `virginia` can match VA; `arkansas` matches AR before `kansas` matches KS
- Tier 2 uses token splitting (split on non-alpha chars) so `invoice.pdf` does NOT match Indiana (`IN` is not a standalone token in `invoice`)
- Tier 3 skips states with names ≤5 chars (Ohio, Iowa, Utah, Maine, Idaho, Texas) to avoid false positives from very short prefixes

**When to edit this file:**
- A state changes its department name → update `dept` in `STATES`
- A state adds an online lookup → update `type` and `url` in `STATES`
- You want to adjust the prefix threshold for Tier 3 matching → change `0.6` in `match_state_from_filename()`

---

### `site_generator.py` — HTML Renderer

**What it does:** One function, `render(record, slug, asset_map, states)`. Loads `templates/index.html.j2`, injects all the agent's data as Jinja2 variables, and returns the complete HTML as a string.

**Variables available in the template:**

| Variable | Source | Example |
|---|---|---|
| `agent_name` | Airtable `name` field | `"Jude Wakim"` |
| `agency_name` | Airtable `agency_name` field | `"Wakim Wealth"` |
| `agent_email` | Airtable `email` field | `"agent@example.com"` |
| `agent_npn` | Airtable `npn` field | `"22168646"` |
| `agent_bio` | Airtable `bio` field | `"Licensed in FL and TX..."` |
| `primary_color` | Airtable `primary_color` field | `"#1a3a5c"` |
| `calendly_url` | Airtable `calendly_url` field | `"https://calendly.com/..."` |
| `profile_pic` | S3 relative path | `"profile.jpg"` |
| `logo_full` | S3 relative path | `"logo-full.png"` |
| `logo_icon` | S3 relative path | `"logo-icon.png"` |
| `carriers_img` | S3 relative path or `None` | `"carriers.jpg"` |
| `states` | List of state dicts | see `state_data.py` above |
| `year` | Hardcoded | `"2026"` |
| `site_url` | Built from slug | `"https://jude-wakim.verifyanagent.com"` |

**When to edit this file:**
- To add a new Airtable field to the template context — add it to the `context` dict here, then use it in `index.html.j2`
- To change the `year` in the footer from hardcoded to dynamic
- To change how `primary_color` is normalized (currently strips `#` if missing)

---

### `templates/index.html.j2` — The Agent Website Template

**What it is:** A Jinja2 HTML template. Every agent's site is generated from this one file with their specific data substituted in. Uses `{{ variable }}` for values and `{% for %}` / `{% if %}` for logic.

**When to edit this file:**
- To change the layout, design, or copy of the generated agent sites
- To add a new section (e.g. testimonials, a contact form)
- To use a new variable — add the variable to `site_generator.py`'s context dict first, then use it here
- **After editing:** redeploy (the template is bundled in the Lambda zip)

---

### `templates/style.css` — Agent Site Stylesheet

**What it is:** All CSS for the generated agent sites. Uses CSS custom properties (`--blue`, `--ink`, `--border`, etc.) defined at the top so the whole palette is in one place.

**When to edit:** Any visual change to agent sites — colors, typography, layout, spacing, card styles, button styles.

**After editing:** redeploy.

---

### `templates/script.js` — Agent Site Frontend JS

**What it is:** Client-side JavaScript for the agent sites. Handles the certificate PDF lightbox (click to zoom), Calendly widget initialization, and any other interactive behavior.

**When to edit:** To add or change interactive behavior on agent sites.

**After editing:** redeploy.

---

### `requirements.txt` — Python Dependencies

```
jinja2==3.1.4
requests==2.31.0
stripe==10.4.0
```

**When to edit:** Only when adding a new Python library. After editing, you must re-run the pip install step before deploying (see Deployment section below).

---

## Environment Variables (Lambda Configuration)

Set these in the Lambda console under **Configuration → Environment variables**. Never commit these to the repo.

| Variable | Where to get it | What it's for |
|---|---|---|
| `AIRTABLE_TOKEN` | Airtable → Account → Developer Hub → Personal Access Token | Authenticate all Airtable API calls |
| `AIRTABLE_BASE_ID` | Airtable base URL — the `appXXXXXXXX` segment | Which Airtable base to read/write |
| `STRIPE_WEBHOOK_SECRET` | Stripe Dashboard → Developers → Webhooks → your endpoint → Signing secret | Verify webhooks are really from Stripe |
| `S3_BUCKET` | AWS S3 console — your bucket name | Where agent sites and assets are stored |

---

## Airtable Form Fields

The Lambda reads these fields from the `Agents` table. Field names must match exactly.

| Airtable field name | Type | Required | Description |
|---|---|---|---|
| `email` | Email | Yes | Used to match the Stripe payment to this record |
| `name` | Single line text | Yes | Agent's full name — also used to generate the subdomain slug |
| `agency_name` | Single line text | No | Falls back to `name` if empty |
| `npn` | Number | Yes | National Producer Number — used to build verify URLs |
| `bio` | Long text | No | Short bio shown on the verification page |
| `primary_color` | Single line text | No | Hex color for branding, e.g. `#1a3a5c`. Defaults to dark navy. |
| `calendly_url` | URL | No | Full Calendly link for the "Schedule a Call" button |
| `states` | Multiple select | Yes | State abbreviations the agent is licensed in (e.g. FL, TX, SC) |
| `profile_pic` | Attachment | Yes | Headshot photo — circular crop, ideally square |
| `logo_full` | Attachment | Yes | Full horizontal logo |
| `logo_icon` | Attachment | No | Square/icon version of logo. Falls back to `logo_full`. |
| `carriers_img` | Attachment | No | Image showing carrier logos. Section hidden if not uploaded. |
| `cert_uploads` | Attachment | Yes | One PDF per licensed state. Filename must reference the state (see below). |
| `payment_status` | Single line text | — | Written by Lambda: `"paid"` |
| `site_status` | Single line text | — | Written by Lambda: `"building"` → `"built"` or `"error"` |
| `site_url` | URL | — | Written by Lambda: the live site URL |
| `build_notes` | Long text | — | Written by Lambda: warnings and errors from the build |

### Certificate PDF Naming

Agents can name their cert files anything that references the state. All of these work for Florida:

```
FL.pdf
fl.pdf
FL-cert.pdf
florida.pdf
florida-cert.pdf
floridadeptofinsurance-48945.pdf
floridaDFS.pdf
```

Files that don't reference any state are skipped and logged in `build_notes`.

---

## Deployment

### Normal deploy (edited Python files or templates only — no new dependencies)

```powershell
$root = "C:\Users\wjude\iCloudDrive\Documents\Work\WakimWorks\verifyanagent-lambda"

# 1. Copy updated source files into the package folder
Copy-Item "$root\handler.py"         "$root\package\handler.py"         -Force
Copy-Item "$root\airtable_client.py" "$root\package\airtable_client.py" -Force
Copy-Item "$root\stripe_verifier.py" "$root\package\stripe_verifier.py" -Force
Copy-Item "$root\s3_manager.py"      "$root\package\s3_manager.py"      -Force
Copy-Item "$root\state_data.py"      "$root\package\state_data.py"      -Force
Copy-Item "$root\site_generator.py"  "$root\package\site_generator.py"  -Force

# 2. Copy updated templates into the package folder
Copy-Item "$root\templates\index.html.j2" "$root\package\templates\index.html.j2" -Force
Copy-Item "$root\templates\style.css"     "$root\package\templates\style.css"     -Force
Copy-Item "$root\templates\script.js"     "$root\package\templates\script.js"     -Force

# 3. Remove old zip, create new one
Remove-Item "$root\package\lambda.zip" -ErrorAction SilentlyContinue
Compress-Archive -Path "$root\package\*" -DestinationPath "$root\package\lambda.zip"

# 4. Deploy
aws lambda update-function-code --function-name YOUR_FUNCTION_NAME --zip-file fileb://"$root\package\lambda.zip"

# 5. Wait for deploy to finish
aws lambda wait function-updated --function-name YOUR_FUNCTION_NAME
Write-Host "Deploy complete."
```

---

### Deploy with new dependencies (edited `requirements.txt`)

You must install the new packages into `package/` first. This requires Python installed locally.

```powershell
$root = "C:\Users\wjude\iCloudDrive\Documents\Work\WakimWorks\verifyanagent-lambda"

# 1. Install all dependencies fresh into package/
pip install -r "$root\requirements.txt" --target "$root\package" --upgrade

# 2. Then follow steps 1–5 from the normal deploy above
```

> **Note:** Lambda runs on Amazon Linux (x86_64). If you install packages on Windows that have compiled C extensions (e.g. `numpy`, `cryptography`), you may need to build them on Linux or use a Docker container matching the Lambda runtime (`python3.11`). The current dependencies (jinja2, requests, stripe) are pure Python and install fine from Windows.

---

## Testing

### Check a specific filename will match correctly

Open a Python shell in the project root:

```powershell
cd "C:\Users\wjude\iCloudDrive\Documents\Work\WakimWorks\verifyanagent-lambda"
python
```

```python
from state_data import match_state_from_filename

test_files = [
    "FL.pdf",
    "florida-cert.pdf",
    "floridadeptofinsurance-48945.pdf",
    "new-york-license.pdf",
    "louisian-cert.pdf",
    "invoice.pdf",           # should return None
    "final-expense.pdf",     # should return None
]

for f in test_files:
    print(f"{f:45} → {match_state_from_filename(f)}")
```

### Trigger a test build in Lambda

1. Go to AWS Lambda console → your function → **Test** tab
2. Create a test event that mimics what Stripe sends (a `checkout.session.completed` event with a customer email matching a record in your Airtable)
3. Run the test and check the **Execution result** and **CloudWatch logs**

In CloudWatch you should see lines like:
```
Uploaded cert: agents/jude-wakim/certs/FL.pdf  (matched from 'florida-cert.pdf')
```

### Read build notes after a run

In Airtable, open the agent's record and check the `build_notes` field. Any skipped files, missing assets, or states that couldn't get a verify URL are all listed there.

---

## Architecture Notes

- **No database** — Airtable is the source of truth for agent data. Lambda is stateless.
- **S3 as a static host** — Agent sites are plain HTML/CSS/JS files served directly from S3 via CloudFront or S3 website hosting. There is no web server.
- **One Lambda invocation = one agent site** — Lambda is triggered once per Stripe payment. Builds take ~5–15 seconds depending on how many cert PDFs are uploaded.
- **Errors don't crash the build** — Non-fatal issues (missing cert, state with no verify URL) are collected in the `errors` list throughout the build and written to `build_notes` at the end. Only catastrophic failures (S3 permissions error, template syntax error) stop the build early.
- **The `package/` folder is the deploy artifact** — Never edit files directly inside `package/`. Always edit the source files in the root, then copy them into `package/` and redeploy.
