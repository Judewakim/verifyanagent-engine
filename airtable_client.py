# airtable_client.py
import os
import requests

# These values come from Lambda's environment variables (set in Step 17)
AIRTABLE_TOKEN = None   # loaded lazily from env
AIRTABLE_BASE_ID = None
TABLE_NAME = "Agents"
BASE_URL = "https://api.airtable.com/v0"

def _get_headers():
    """Build the authorization headers for every Airtable API call."""
    token = os.environ['AIRTABLE_TOKEN']
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

def _get_base_id():
    return os.environ['AIRTABLE_BASE_ID']

def find_by_email(email):
    """
    Search the Agents table for a record whose email matches.
    Returns the full record dict (including 'id' and 'fields') or None if not found.

    The filterByFormula uses Airtable's formula language.
    LOWER() makes the match case-insensitive so 'John@Gmail.com' matches 'john@gmail.com'.
    """
    url = f"{BASE_URL}/{_get_base_id()}/{TABLE_NAME}"
    # Escape single quotes in the email to prevent formula injection
    safe_email = email.lower().replace("'", "\\'")
    params = {
        "filterByFormula": f"LOWER({{email}}) = '{safe_email}'"
    }
    response = requests.get(url, headers=_get_headers(), params=params, timeout=10)
    response.raise_for_status()  # raises an exception if Airtable returns an error

    records = response.json().get('records', [])
    if not records:
        return None
    return records[0]  # return the first match

def list_all(fields=None):
    """
    Return every record in the Agents table (following Airtable's pagination).

    fields: optional list of field names to fetch (lightens the payload for the
            admin list view, e.g. ['name', 'email', 'site_status']). None = all fields.

    Returns a list of record dicts, each with 'id' and 'fields'.
    """
    url = f"{BASE_URL}/{_get_base_id()}/{TABLE_NAME}"
    records = []
    offset = None
    while True:
        params = {'pageSize': 100}
        if fields:
            params['fields[]'] = fields
        if offset:
            params['offset'] = offset
        response = requests.get(url, headers=_get_headers(), params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        records.extend(data.get('records', []))
        offset = data.get('offset')
        if not offset:
            break
    return records

def get_by_id(record_id):
    """
    Fetch a single Agents record by its Airtable record id (recXXXX).
    Returns the full record dict (with 'id' and 'fields').
    """
    url = f"{BASE_URL}/{_get_base_id()}/{TABLE_NAME}/{record_id}"
    response = requests.get(url, headers=_get_headers(), timeout=10)
    response.raise_for_status()
    return response.json()

def set_attachment(record_id, field_name, url, filename):
    """
    Replace an attachment field with a single file at the given URL.

    Airtable fetches and re-hosts the file from `url` (which must be reachable for
    a short window — a presigned S3 GET URL works). Passing a one-element list
    REPLACES the field's contents, so the build's attachments[0] reads the new file.
    """
    return update(record_id, {field_name: [{'url': url, 'filename': filename}]})

def update(record_id, fields):
    """
    Update specific fields on an existing Airtable record.
    Only the fields listed in the 'fields' dict are changed - others are untouched.

    Example: update('recXXXXX', {'site_status': 'built', 'site_url': 'https://...'})
    """
    url = f"{BASE_URL}/{_get_base_id()}/{TABLE_NAME}/{record_id}"
    payload = {"fields": fields}
    response = requests.patch(url, headers=_get_headers(), json=payload, timeout=10)
    response.raise_for_status()
    return response.json()

def create_error_record(email, error_message):
    """
    When a Stripe payment comes in but we can't find a matching form submission,
    create a new Airtable record to flag this for manual investigation.
    This will trigger Airtable Automation 2 (site_status = 'error'  email Jude).
    """
    url = f"{BASE_URL}/{_get_base_id()}/{TABLE_NAME}"
    payload = {
        "fields": {
            "email": email,
            "payment_status": "paid",
            "site_status": "error",
            "build_notes": error_message
        }
    }
    response = requests.post(url, headers=_get_headers(), json=payload, timeout=10)
    response.raise_for_status()
    return response.json()
