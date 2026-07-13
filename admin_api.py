# admin_api.py — the admin web editor's backend (a SECOND Lambda function).
#
# Behind its own API Gateway HTTP API (payload format v2), reached from the
# single-page admin app at admin.verifyanagent.com. It lets one operator (Jude)
# log in with a password, edit any agent's Airtable fields, upload images, and
# publish the changes to the live site by calling the shared builder.build_site().
#
# Routing is done in-code from one catch-all ($default) route, so API Gateway
# only needs a single route pointing here.
#
# Auth model: one shared password (ADMIN_PASSWORD). On login we mint a stateless,
# HMAC-signed, expiring bearer token (signed with ADMIN_SESSION_SECRET); every
# other route verifies it. Single operator, so there's no per-user accounts or
# token revocation beyond rotating the secret.
import os
import json
import time
import hmac
import base64
import hashlib
import urllib.parse
from pathlib import Path

import requests
import boto3

import airtable_client
import s3_manager
import builder
import state_data

# SSM client for the admin credential (stored privately, see CRED_PARAM below).
ssm = boto3.client('ssm')

# ── Config ────────────────────────────────────────────────────────────────────
TOKEN_TTL_SECONDS = 12 * 60 * 60   # 12 hours

# There is exactly ONE admin account — Jude's. Login requires this email AND the
# password. Hardcoding the identity here means no other account can ever be
# created. Change this one line if you sign in with a different email.
ADMIN_EMAIL = 'you@example.com'

# The password is NOT an env var — it's set by Jude on first sign-in and can be
# changed in the portal. We store the salted PBKDF2 hash in SSM Parameter Store as a
# KMS-encrypted SecureString. It used to live in an S3 object under _admin/, but the
# apex host serves the bucket ROOT, so that object was web-reachable
# (verifyanagent.com/_admin/credentials.json). SSM is private — nothing in the HTTP
# path can return it.
CRED_PARAM        = '/verifyanagent/admin/credentials'
PBKDF2_ITERATIONS = 200_000
MIN_PASSWORD_LEN  = 8

# Fields the editor is allowed to write. Excludes only the status fields (owned by
# the build). NOTE: the slug/subdomain comes from the 'subdomain' field when set,
# else from 'name'. Changing whichever one is in effect moves the client to a new
# URL (and a new S3 folder) on the next publish (the UI warns about this).
EDITABLE_FIELDS = {
    'name',
    'subdomain',
    'npn',
    'bio',
    'agency_name',
    'primary_color',
    'calendly_url',
    'states',
    'license_numbers_override',
    'verify_url_override',
    'hide_certificates',
}

# Attachment (image) fields, each holding exactly one file.
IMAGE_FIELDS = {'profile_pic', 'logo_full', 'logo_icon', 'carriers_img'}

# Fields the PUBLIC signup form may set when creating a brand-new record. Same as
# the editor's whitelist, plus 'email' (which the editor treats as read-only but a
# new signup must provide). Status fields are set by the server, never the client.
SIGNUP_FIELDS = EDITABLE_FIELDS | {'email'}

# Certificate PDFs live in a separate MULTIPLE-attachment field. The build matches
# each file to a state by its filename, so we name staged certs '{ABBREV}.pdf'.
CERT_FIELD = 'cert_uploads'
_ALLOWED_CERT_EXTS = {'.pdf'}

# Slugs that may never be claimed as a subdomain (they collide with infra/pages).
RESERVED_SLUGS = {
    'admin', 'www', 'api', 'app', 'mail', 'ftp', 'assets', 'static',
    'test', 'staging', 'get-started', 'getstarted', 'signup', 'index',
}

# Fields surfaced (read-only) alongside the editable ones in the detail view.
# build_notes_ack holds the build_notes text an admin has "marked as reviewed" — the
# detail view compares it against the current build_notes to decide whether the page
# still needs review (see renderReviewBanner / _list_agents).
_READ_FIELDS = ('name', 'email', 'npn', 'site_status', 'site_url', 'build_notes', 'build_notes_ack')

_ALLOWED_IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.gif', '.svg', '.webp'}


# ── HTTP helpers ──────────────────────────────────────────────────────────────
# The admin portal (admin.verifyanagent.com) AND the public signup form on the
# apex site both call this API from the browser, so CORS must allow both origins.
# We reflect the request's Origin only if it's on the allowlist (env override:
# ALLOWED_ORIGINS, comma-separated). _resolved_origin is set per-invocation at the
# top of handler() — Lambda runs one invocation start-to-finish, so a module global
# is safe here and saves threading the event through every _respond() call.
_DEFAULT_ALLOWED_ORIGINS = (
    'https://admin.verifyanagent.com',
    'https://verifyanagent.com',
    'https://www.verifyanagent.com',
)
_resolved_origin = '*'


def _allowed_origins():
    env = os.environ.get('ALLOWED_ORIGINS')
    if env:
        return tuple(o.strip() for o in env.split(',') if o.strip())
    origins = set(_DEFAULT_ALLOWED_ORIGINS)
    legacy = os.environ.get('ADMIN_CORS_ORIGIN')
    if legacy and legacy != '*':
        origins.add(legacy)
    return tuple(sorted(origins))


def _resolve_origin(event):
    """Echo the request Origin only when it's allowed; else fall back to the first."""
    origin = _header(event, 'origin') or ''
    allowed = _allowed_origins()
    if origin in allowed:
        return origin
    return allowed[0] if allowed else '*'


def _cors_headers():
    return {
        'Access-Control-Allow-Origin':  _resolved_origin,
        'Access-Control-Allow-Headers': 'Authorization, Content-Type',
        'Access-Control-Allow-Methods': 'GET, POST, PATCH, OPTIONS',
        'Access-Control-Max-Age':       '3600',
    }


def _respond(status, body=None):
    headers = {'Content-Type': 'application/json', **_cors_headers()}
    return {
        'statusCode': status,
        'headers': headers,
        'body': '' if body is None else json.dumps(body),
    }


def _request_method(event):
    return event.get('requestContext', {}).get('http', {}).get('method', '')


def _request_path(event):
    # HTTP API v2: rawPath is the request path (no stage prefix on $default).
    return event.get('rawPath') or event.get('requestContext', {}).get('http', {}).get('path', '')


def _parse_body(event):
    raw = event.get('body') or ''
    if event.get('isBase64Encoded'):
        raw = base64.b64decode(raw).decode('utf-8')
    if not raw:
        return {}
    return json.loads(raw)


def _header(event, name):
    # HTTP API v2 lower-cases all header keys.
    return (event.get('headers') or {}).get(name.lower())


# ── Auth: password → signed, expiring bearer token ───────────────────────────
def _b64url(b):
    return base64.urlsafe_b64encode(b).rstrip(b'=').decode('ascii')


def _sign(payload):
    secret = os.environ['ADMIN_SESSION_SECRET'].encode('utf-8')
    return hmac.new(secret, payload.encode('utf-8'), hashlib.sha256).hexdigest()


def _make_token():
    exp = str(int(time.time()) + TOKEN_TTL_SECONDS)
    return f"{_b64url(exp.encode())}.{_sign(exp)}", int(exp)


def _valid_token(token):
    try:
        exp_b64, sig = token.split('.', 1)
        # restore padding
        exp = base64.urlsafe_b64decode(exp_b64 + '=' * (-len(exp_b64) % 4)).decode()
    except Exception:
        return False
    if not hmac.compare_digest(_sign(exp), sig):
        return False
    return int(exp) > int(time.time())


def _email_ok(email):
    return hmac.compare_digest((email or '').strip().lower(), ADMIN_EMAIL.lower())


def _hash_password(password, salt_hex, iterations):
    dk = hashlib.pbkdf2_hmac('sha256', (password or '').encode('utf-8'),
                             bytes.fromhex(salt_hex), iterations)
    return dk.hex()


def _load_credentials():
    """Return the stored credential dict, or None if no password has been set yet.
    The value is a KMS-encrypted SecureString in SSM Parameter Store (private)."""
    try:
        resp = ssm.get_parameter(Name=CRED_PARAM, WithDecryption=True)
        return json.loads(resp['Parameter']['Value'])
    except ssm.exceptions.ParameterNotFound:
        return None


def _save_credentials(password):
    salt = os.urandom(16).hex()
    cred = {
        'version':    1,
        'salt':       salt,
        'hash':       _hash_password(password, salt, PBKDF2_ITERATIONS),
        'iterations': PBKDF2_ITERATIONS,
        'updated_at': int(time.time()),
    }
    ssm.put_parameter(
        Name=CRED_PARAM,
        Value=json.dumps(cred),
        Type='SecureString',
        Overwrite=True,
    )


def _verify_password(password, cred):
    if not cred:
        return False
    computed = _hash_password(password, cred['salt'], cred.get('iterations', PBKDF2_ITERATIONS))
    return hmac.compare_digest(computed, cred['hash'])


def _require_auth(event):
    """Return None if authorized, else a 401 response dict."""
    header = _header(event, 'authorization') or ''
    token = header[7:] if header.lower().startswith('bearer ') else ''
    if not token or not _valid_token(token):
        return _respond(401, {'error': 'unauthorized'})
    return None


# ── Route handlers ────────────────────────────────────────────────────────────
def _status(event):
    """Public: tells the login page whether a password has been set yet."""
    return _respond(200, {
        'initialized': _load_credentials() is not None,
        'email':       ADMIN_EMAIL,
    })


def _login(event):
    body = _parse_body(event)
    if not _email_ok(body.get('email', '')):
        return _respond(401, {'error': 'invalid email or password'})
    cred = _load_credentials()
    if cred is None:
        return _respond(409, {'error': 'no password set yet', 'needsSetup': True})
    if not _verify_password(body.get('password', ''), cred):
        return _respond(401, {'error': 'invalid email or password'})
    token, exp = _make_token()
    return _respond(200, {'token': token, 'expiresAt': exp})


def _set_initial_password(event):
    """Public, but only works once: sets the password on first sign-in."""
    body = _parse_body(event)
    if not _email_ok(body.get('email', '')):
        return _respond(401, {'error': 'invalid email'})
    if _load_credentials() is not None:
        return _respond(409, {'error': 'a password is already set — use change password'})
    password = body.get('password', '')
    if len(password) < MIN_PASSWORD_LEN:
        return _respond(400, {'error': f'password must be at least {MIN_PASSWORD_LEN} characters'})
    _save_credentials(password)
    token, exp = _make_token()
    return _respond(200, {'token': token, 'expiresAt': exp})


def _change_password(event):
    """Auth required: change the password from the portal settings."""
    body = _parse_body(event)
    cred = _load_credentials()
    if cred is None:
        return _respond(409, {'error': 'no password set yet'})
    if not _verify_password(body.get('currentPassword', ''), cred):
        return _respond(401, {'error': 'current password is incorrect'})
    new_password = body.get('newPassword', '')
    if len(new_password) < MIN_PASSWORD_LEN:
        return _respond(400, {'error': f'password must be at least {MIN_PASSWORD_LEN} characters'})
    _save_credentials(new_password)
    return _respond(200, {'ok': True})


def _list_agents(event):
    _fields = ['name', 'subdomain', 'email', 'site_status', 'site_url', 'build_notes', 'build_notes_ack']
    try:
        records = airtable_client.list_all(fields=_fields)
    except requests.HTTPError:
        # build_notes_ack may not exist yet — Airtable 422s on an unknown field name,
        # which would otherwise 500 the whole client list. Retry without it; the
        # review-acknowledgement feature stays dormant until the field is added.
        records = airtable_client.list_all(fields=[f for f in _fields if f != 'build_notes_ack'])
    agents = []
    for r in records:
        f = r['fields']
        name = f.get('name', '')
        status = f.get('site_status', '')
        notes = (f.get('build_notes') or '').strip()
        ack = (f.get('build_notes_ack') or '').strip()
        # A page "needs review" when the build errored or left warnings. The build
        # writes 'Build completed with no issues.' when clean, so anything else is
        # a real note. (Keeps the trigger in sync with builder.py's build_notes.)
        # An admin can "mark as reviewed", which stores the current build_notes in
        # build_notes_ack — while the notes still match that ack, the flag is cleared.
        # A new/changed warning on the next publish no longer matches, so it re-flags.
        raw_needs = status == 'error' or (bool(notes) and notes != 'Build completed with no issues.')
        needs_review = raw_needs and notes != ack
        agents.append({
            'id':           r['id'],
            'name':         name,
            'email':        f.get('email', ''),
            'slug':         s3_manager.resolve_slug(f),
            'site_status':  status,
            'site_url':     f.get('site_url', ''),
            'needs_review': needs_review,
            'build_notes':  notes if needs_review else '',
        })
    agents.sort(key=lambda a: a['name'].lower())
    return _respond(200, {'agents': agents})


def _list_agents_public(event):
    """Public, unauthenticated: published agents only, with the minimal fields the
    homepage agent search needs. No email, no record id — just what already appears
    on each agent's live public site."""
    # This is public, non-credentialed, read-only data and it's fetched as a simple
    # GET (no preflight), so allow any origin — unlike the admin routes, which keep
    # the strict allowlist. Lets the search work from the apex site AND local dev.
    global _resolved_origin
    _resolved_origin = '*'
    records = airtable_client.list_all(
        fields=['name', 'subdomain', 'site_status', 'site_url', 'states', 'profile_pic']
    )
    agents = []
    for r in records:
        f = r['fields']
        if f.get('site_status') != 'built':
            continue
        slug = s3_manager.resolve_slug(f)
        # The profile photo is published to the agent's own site as profile.<ext>
        # (see s3_manager.process_attachment). Point at that stable, non-expiring
        # URL — Airtable attachment URLs expire and must not be handed to the browser.
        atts = f.get('profile_pic') or []
        ext = Path(atts[0].get('filename', '')).suffix.lower() if atts else ''
        ext = ext or '.jpg'
        site_url = f.get('site_url') or f"https://{slug}.verifyanagent.com"
        agents.append({
            'name':            f.get('name', ''),
            'slug':            slug,
            'states':          f.get('states', []) or [],
            'site_url':        site_url,
            'profile_pic_url': f"https://{slug}.verifyanagent.com/profile{ext}",
        })
    agents.sort(key=lambda a: a['name'].lower())
    return _respond(200, {'agents': agents})


def _first_attachment_url(attachments):
    if attachments and isinstance(attachments, list):
        return attachments[0].get('url')
    return None


def _verify_home(url):
    """The licensing board's homepage origin for a state's verify-URL template —
    shown as a placeholder hint in the admin's custom-verify-link box so the
    operator knows where to go look the agent up. '' when the state has no
    configured URL (e.g. NY)."""
    if not url:
        return ''
    p = urllib.parse.urlparse(url)
    if not p.scheme or not p.netloc:
        return ''
    return f"{p.scheme}://{p.netloc}/"


def _cert_states(fields):
    """Ordered list of state abbrevs the agent already has a cert PDF for, matched
    from the cert_uploads attachment filenames the SAME way the build does — so the
    admin UI shows an accurate 'uploaded / not set' per state."""
    out = []
    for att in fields.get(CERT_FIELD, []) or []:
        ab = state_data.match_state_from_filename(att.get('filename', ''))
        if ab and ab not in out:
            out.append(ab)
    return out


def _get_agent(event, record_id):
    record = airtable_client.get_by_id(record_id)
    f = record.get('fields', {})

    editable = {k: f.get(k) for k in EDITABLE_FIELDS}
    # states defaults to a list for the UI
    editable['states'] = f.get('states', []) or []

    images = {field: _first_attachment_url(f.get(field, [])) for field in IMAGE_FIELDS}

    return _respond(200, {
        'id':       record['id'],
        'slug':     s3_manager.resolve_slug(f),
        'read':     {k: f.get(k) for k in _READ_FIELDS},
        'editable': editable,
        'images':   images,
        # States that already have a cert PDF, so the UI can label each row.
        'cert_states': _cert_states(f),
        # Reference data so the UI can render the state picker / labels. verify_home
        # is the board homepage the operator would look the agent up on, used as the
        # custom-verify-link placeholder.
        'all_states': [
            {'abbrev': ab, 'name': info['name'], 'verify_home': _verify_home(info.get('url'))}
            for ab, info in sorted(state_data.STATES.items(), key=lambda x: x[1]['name'])
        ],
    })


def _coerce_npn(fields):
    """NPN is a TEXT field in this Airtable base — send it as a trimmed string (or
    None to clear it). It previously coerced to int, but a text column rejects an
    integer with a 422 INVALID_VALUE_FOR_COLUMN."""
    if 'npn' in fields:
        npn = str(fields['npn'] if fields['npn'] is not None else '').strip()
        fields['npn'] = npn or None
    return fields


def _patch_agent(event, record_id):
    body = _parse_body(event)
    updates = {k: v for k, v in body.items() if k in EDITABLE_FIELDS}
    if not updates:
        return _respond(400, {'error': 'no editable fields supplied'})

    _coerce_npn(updates)

    airtable_client.update(record_id, updates)
    return _respond(200, {'ok': True, 'updated': sorted(updates.keys())})


def _image_upload_url(event, record_id):
    """Step 1: hand the browser a presigned PUT URL to send image bytes straight to S3."""
    body = _parse_body(event)
    field = body.get('field')
    filename = body.get('filename', '')
    content_type = body.get('contentType') or 'application/octet-stream'

    if field not in IMAGE_FIELDS:
        return _respond(400, {'error': f'unknown image field: {field}'})
    ext = Path(filename).suffix.lower()
    if ext not in _ALLOWED_IMAGE_EXTS:
        return _respond(400, {'error': f'unsupported image type: {ext or "(none)"}'})

    record = airtable_client.get_by_id(record_id)
    slug = s3_manager.resolve_slug(record['fields'])
    key = f"agents/{slug}/_uploads/{field}{ext}"

    upload_url = s3_manager.s3.generate_presigned_url(
        'put_object',
        Params={'Bucket': os.environ['S3_BUCKET'], 'Key': key, 'ContentType': content_type},
        ExpiresIn=900,
    )
    return _respond(200, {'uploadUrl': upload_url, 'key': key, 'contentType': content_type})


def _image_attach(event, record_id):
    """Step 2: after the browser PUT the bytes to S3, point the Airtable field at them."""
    body = _parse_body(event)
    field = body.get('field')
    key = body.get('key')
    filename = body.get('filename') or Path(key or '').name

    if field not in IMAGE_FIELDS:
        return _respond(400, {'error': f'unknown image field: {field}'})
    if not key:
        return _respond(400, {'error': 'missing S3 key'})

    # Presigned GET so Airtable can fetch the staged file without a public bucket.
    get_url = s3_manager.s3.generate_presigned_url(
        'get_object',
        Params={'Bucket': os.environ['S3_BUCKET'], 'Key': key},
        ExpiresIn=3600,
    )
    airtable_client.set_attachment(record_id, field, get_url, filename)
    return _respond(200, {'ok': True, 'field': field})


def _publish(event, record_id):
    record = airtable_client.get_by_id(record_id)
    result = builder.build_site(record)
    return _respond(200 if result['ok'] else 500, {
        'ok':            result['ok'],
        'site_url':      result['site_url'],
        'warnings':      result['warnings'],
        'warning_count': result['warning_count'],
    })


def _mark_reviewed(event, record_id):
    """Acknowledge the current build warnings so the 'Needs review' flag clears.
    Copies the record's CURRENT build_notes into build_notes_ack (server-side, not a
    client-supplied value). The flag stays cleared while the notes match this ack; a
    new/changed warning on a later publish no longer matches and re-flags."""
    record = airtable_client.get_by_id(record_id)
    notes  = (record['fields'].get('build_notes') or '').strip()
    try:
        airtable_client.update(record_id, {'build_notes_ack': notes})
    except Exception as e:
        return _respond(500, {'error': "Could not save review acknowledgement "
                              f"(does the 'build_notes_ack' Long-text field exist in Airtable?): {e}"})
    return _respond(200, {'ok': True})


# ── Public signup (the brand-styled creation form on the apex site) ────────────
# These routes are UNAUTHENTICATED — anyone on verifyanagent.com/signup can hit
# them. Real harm is bounded (a site only builds after Stripe payment), but to
# keep junk out we use a honeypot field + Cloudflare Turnstile, and the image
# routes only accept records still in the 'submitted' state.
def _source_ip(event):
    return event.get('requestContext', {}).get('http', {}).get('sourceIp')


def _verify_turnstile(event, token):
    """Verify a Cloudflare Turnstile token. If no secret is configured (e.g. local
    dev), verification is skipped — set TURNSTILE_SECRET in production."""
    secret = os.environ.get('TURNSTILE_SECRET')
    if not secret:
        print('WARNING: TURNSTILE_SECRET not set — skipping captcha verification')
        return True
    if not token:
        return False
    try:
        resp = requests.post(
            'https://challenges.cloudflare.com/turnstile/v0/siteverify',
            data={'secret': secret, 'response': token, 'remoteip': _source_ip(event)},
            timeout=10,
        )
        return bool(resp.json().get('success'))
    except Exception as e:
        print(f'Turnstile verification error: {e}')
        return False


def _signup(event):
    """Create a new Agents record from the public form. Returns the new record id
    so the browser can upload images and then redirect to Stripe with it."""
    body = _parse_body(event)

    # Honeypot: a field hidden from humans via CSS. If it's filled, it's a bot.
    if (body.get('company') or '').strip():
        print('Signup rejected: honeypot filled')
        return _respond(400, {'error': 'rejected'})

    if not _verify_turnstile(event, body.get('turnstileToken', '')):
        return _respond(400, {'error': 'captcha verification failed — please try again'})

    fields = {k: v for k, v in body.items() if k in SIGNUP_FIELDS}

    email = (fields.get('email') or '').strip()
    if not email or '@' not in email:
        return _respond(400, {'error': 'a valid email is required'})
    fields['email'] = email

    if not (fields.get('name') or '').strip():
        return _respond(400, {'error': 'name is required'})

    if not str(fields.get('npn') or '').strip():
        return _respond(400, {'error': 'NPN is required'})

    _coerce_npn(fields)

    # Initial status for a fresh, unpaid signup. These MUST match the predefined
    # Airtable single-select options exactly. The Stripe webhook later sets
    # payment_status='paid', and the build advances site_status from here.
    fields['payment_status'] = 'pending'
    fields['site_status'] = 'not started'

    record = airtable_client.create(fields)
    return _respond(200, {'recordId': record['id']})


def _signup_editable(record_id):
    """Public upload routes may only touch a record that hasn't been paid for yet,
    so they can't be aimed at a live, paid agent's record. A fresh signup has no
    payment_status until the Stripe webhook sets it to 'paid'."""
    record = airtable_client.get_by_id(record_id)
    return record.get('fields', {}).get('payment_status') != 'paid'


def _signup_image_url(event, record_id):
    if not _signup_editable(record_id):
        return _respond(403, {'error': 'not a pending signup'})
    return _image_upload_url(event, record_id)


def _signup_image(event, record_id):
    if not _signup_editable(record_id):
        return _respond(403, {'error': 'not a pending signup'})
    return _image_attach(event, record_id)


def _check_subdomain(event):
    """Tell the signup form whether a desired page address is free. Resolves the
    slug the same way the build does (subdomain if given, else slugified name), then
    checks it against reserved words and every existing agent's resolved slug."""
    qs = event.get('queryStringParameters') or {}
    value = (qs.get('value') or '').strip()
    name = (qs.get('name') or '').strip()
    slug = s3_manager.resolve_slug({'subdomain': value, 'name': name})

    if not slug:
        return _respond(200, {'slug': '', 'available': False, 'reason': 'empty'})
    if slug in RESERVED_SLUGS:
        return _respond(200, {'slug': slug, 'available': False, 'reason': 'reserved'})
    for r in airtable_client.list_all(fields=['subdomain', 'name']):
        if s3_manager.resolve_slug(r.get('fields', {})) == slug:
            return _respond(200, {'slug': slug, 'available': False, 'reason': 'taken'})
    return _respond(200, {'slug': slug, 'available': True})


def _cert_url_core(event, record_id):
    """Presign a PUT for one state's certificate PDF. Shared by the public signup
    flow and the authenticated admin editor — the caller enforces access first."""
    body = _parse_body(event)
    abbrev = (body.get('abbrev') or '').strip().upper()
    filename = body.get('filename', '')
    content_type = body.get('contentType') or 'application/pdf'

    if abbrev not in state_data.STATES:
        return _respond(400, {'error': f'unknown state: {abbrev}'})
    ext = Path(filename).suffix.lower()
    if ext not in _ALLOWED_CERT_EXTS:
        return _respond(400, {'error': 'certificates must be PDF files'})

    record = airtable_client.get_by_id(record_id)
    slug = s3_manager.resolve_slug(record['fields'])
    key = f"agents/{slug}/_uploads/certs/{abbrev}.pdf"

    upload_url = s3_manager.s3.generate_presigned_url(
        'put_object',
        Params={'Bucket': os.environ['S3_BUCKET'], 'Key': key, 'ContentType': content_type},
        ExpiresIn=900,
    )
    return _respond(200, {'uploadUrl': upload_url, 'key': key, 'abbrev': abbrev, 'contentType': content_type})


def _signup_cert_url(event, record_id):
    """Step 1 of a cert upload (public signup): presign a PUT for one state's cert."""
    if not _signup_editable(record_id):
        return _respond(403, {'error': 'not a pending signup'})
    return _cert_url_core(event, record_id)


def _signup_certs(event, record_id):
    """Step 2: after the browser PUT each cert to S3, point the multi-attachment
    cert_uploads field at all of them in one shot. Filenames are '{ABBREV}.pdf' so
    the build matches each cert to its state."""
    if not _signup_editable(record_id):
        return _respond(403, {'error': 'not a pending signup'})
    body = _parse_body(event)
    certs = body.get('certs') or []

    items = []
    for c in certs:
        key = c.get('key')
        abbrev = (c.get('abbrev') or '').strip().upper()
        if not key or abbrev not in state_data.STATES:
            continue
        get_url = s3_manager.s3.generate_presigned_url(
            'get_object',
            Params={'Bucket': os.environ['S3_BUCKET'], 'Key': key},
            ExpiresIn=3600,
        )
        items.append({'url': get_url, 'filename': f'{abbrev}.pdf'})

    if not items:
        return _respond(400, {'error': 'no valid certificates supplied'})
    airtable_client.set_attachments(record_id, CERT_FIELD, items)
    return _respond(200, {'ok': True, 'count': len(items)})


# ── Admin cert upload (authenticated; works on already-paid agents) ────────────
# The signup routes above REFUSE paid records and REPLACE the whole cert field —
# right for a brand-new signup, wrong for editing a live agent. These admin routes
# have no pending-only guard (the auth wall in handler() gates them) and MERGE by
# state: uploading a cert for one state swaps just that state's PDF and leaves every
# other state's cert intact.
def _admin_cert_url(event, record_id):
    """Step 1: presign a PUT for one state's certificate PDF (admin editor)."""
    return _cert_url_core(event, record_id)


def _admin_certs(event, record_id):
    """Step 2: after the browser PUT each cert to S3, merge them into cert_uploads.
    Keyed by state — a new cert for a state REPLACES that state's existing PDF and
    leaves the other states' certs untouched (retained by their Airtable id)."""
    body = _parse_body(event)
    certs = body.get('certs') or []

    # The new/replacement certs, keyed by state abbrev.
    new_by_abbrev = {}
    for c in certs:
        key = c.get('key')
        abbrev = (c.get('abbrev') or '').strip().upper()
        if not key or abbrev not in state_data.STATES:
            continue
        get_url = s3_manager.s3.generate_presigned_url(
            'get_object',
            Params={'Bucket': os.environ['S3_BUCKET'], 'Key': key},
            ExpiresIn=3600,
        )
        new_by_abbrev[abbrev] = {'url': get_url, 'filename': f'{abbrev}.pdf'}

    if not new_by_abbrev:
        return _respond(400, {'error': 'no valid certificates supplied'})

    # Retain every existing attachment whose state is NOT being replaced (by its
    # Airtable id); drop the ones a new upload supersedes; then add the new certs.
    record = airtable_client.get_by_id(record_id)
    existing = record.get('fields', {}).get(CERT_FIELD, []) or []
    merged = []
    for att in existing:
        abbrev = state_data.match_state_from_filename(att.get('filename', ''))
        if abbrev in new_by_abbrev:
            continue   # this state is being replaced by a fresh upload
        att_id = att.get('id')
        if att_id:
            merged.append({'id': att_id})   # keep the existing file as-is
    merged.extend(new_by_abbrev.values())

    airtable_client.set_attachments(record_id, CERT_FIELD, merged)
    return _respond(200, {'ok': True, 'count': len(new_by_abbrev), 'total': len(merged)})


# ── Entry point ───────────────────────────────────────────────────────────────
def handler(event, context):
    global _resolved_origin
    _resolved_origin = _resolve_origin(event)

    method = _request_method(event)
    path = _request_path(event).rstrip('/') or '/'

    # CORS preflight
    if method == 'OPTIONS':
        return _respond(204)

    # Public routes (auth bootstrap)
    if method == 'GET' and path == '/admin/status':
        return _route(_status, event)
    if method == 'POST' and path == '/admin/login':
        return _route(_login, event)
    if method == 'POST' and path == '/admin/set-initial-password':
        return _route(_set_initial_password, event)

    # Public agent directory — powers the homepage agent search. No auth: returns
    # only published agents and only the fields already public on their live sites.
    if method == 'GET' and path == '/public/agents':
        return _route(_list_agents_public, event)

    # Public signup routes (the brand-styled creation form on the apex site).
    # No auth — guarded by honeypot + Turnstile (create) and a 'submitted'-state
    # check (image routes). Registered above the _require_auth wall below.
    if method == 'POST' and path == '/signup':
        return _route(_signup, event)
    if method == 'GET' and path == '/signup/check-subdomain':
        return _route(_check_subdomain, event)
    if path.startswith('/signup/'):
        parts = path[len('/signup/'):].split('/')
        record_id = parts[0]
        action = parts[1] if len(parts) > 1 else None
        if record_id and method == 'POST':
            if action == 'image-url':
                return _route(_signup_image_url, event, record_id)
            if action == 'image':
                return _route(_signup_image, event, record_id)
            if action == 'cert-url':
                return _route(_signup_cert_url, event, record_id)
            if action == 'certs':
                return _route(_signup_certs, event, record_id)

    # Everything below requires a valid token
    unauthorized = _require_auth(event)
    if unauthorized:
        return unauthorized

    if method == 'POST' and path == '/admin/change-password':
        return _route(_change_password, event)

    if method == 'GET' and path == '/admin/agents':
        return _route(_list_agents, event)

    # /admin/agents/{id}[/action]
    if path.startswith('/admin/agents/'):
        rest = path[len('/admin/agents/'):]
        parts = rest.split('/')
        record_id = parts[0]
        action = parts[1] if len(parts) > 1 else None

        if record_id:
            if action is None and method == 'GET':
                return _route(_get_agent, event, record_id)
            if action is None and method == 'PATCH':
                return _route(_patch_agent, event, record_id)
            if action == 'image-url' and method == 'POST':
                return _route(_image_upload_url, event, record_id)
            if action == 'image' and method == 'POST':
                return _route(_image_attach, event, record_id)
            if action == 'cert-url' and method == 'POST':
                return _route(_admin_cert_url, event, record_id)
            if action == 'certs' and method == 'POST':
                return _route(_admin_certs, event, record_id)
            if action == 'publish' and method == 'POST':
                return _route(_publish, event, record_id)
            if action == 'review' and method == 'POST':
                return _route(_mark_reviewed, event, record_id)

    return _respond(404, {'error': 'not found', 'path': path, 'method': method})


def _route(fn, event, *args):
    """Call a route handler, converting unexpected errors into a 500 (with CORS)."""
    try:
        return fn(event, *args)
    except Exception as e:
        import traceback
        print(traceback.format_exc())
        return _respond(500, {'error': str(e)})
