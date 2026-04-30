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
