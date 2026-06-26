# handler.py
import json

import stripe_verifier
import airtable_client
import builder


def handler(event, context):
    """
    AWS Lambda entry point.
    Called by API Gateway every time Stripe sends a webhook.

    This function's only job is to verify the webhook, find the matching Airtable
    record, and hand off to builder.build_site() — the shared build pipeline that
    the admin "Publish" button also uses.
    """
    print("=== Lambda triggered ===")

    # ── 1. Verify the request genuinely came from Stripe ─────────────────────
    # If someone sends a fake POST to our API Gateway URL, this stops them cold.
    try:
        stripe_event = stripe_verifier.verify(event)
    except ValueError as e:
        print(f"Stripe verification failed: {e}")
        return {'statusCode': 400, 'body': str(e)}

    # We only care about completed payments — ignore all other Stripe events
    if stripe_event.get('type') != 'checkout.session.completed':
        print(f"Ignoring event type: {stripe_event.get('type')}")
        return {'statusCode': 200, 'body': 'Event type ignored'}

    # ── 2. Pull the identifiers from the Stripe payload ───────────────────────
    # The new signup form passes the Airtable record id as client_reference_id, so
    # we can join the payment to the exact record regardless of which email the
    # customer entered at Stripe. Email is kept only as a fallback (for any legacy
    # or manually-created payment links that don't carry a record id).
    session = stripe_event['data']['object']
    record_id = (session.get('client_reference_id') or '').strip()
    email = (session.get('customer_details') or {}).get('email', '').strip().lower()

    print(f"Processing payment — record_id={record_id or '(none)'} email={email or '(none)'}")

    # ── 3. Find the matching Airtable form submission ─────────────────────────
    record = None
    if record_id:
        # Authoritative join: look the record up directly by its id.
        try:
            record = airtable_client.get_by_id(record_id)
        except Exception as e:
            print(f"client_reference_id {record_id} did not resolve to a record: {e}")
            record = None

    if not record and email:
        # Legacy fallback: match by the email the customer used.
        record = airtable_client.find_by_email(email)

    if not record:
        # Payment received but no record found — create an error record so
        # Airtable Automation 2 fires and emails Jude to investigate.
        print(f"No Airtable record found (record_id={record_id!r}, email={email!r})")
        airtable_client.create_error_record(
            email or '(unknown)',
            f"Payment received (record_id={record_id or 'none'}, email={email or 'none'}) "
            "but no matching form submission was found. Please match manually and update this record."
        )
        return {'statusCode': 200, 'body': 'No matching form found — error record created'}

    # ── 4. Build the site ─────────────────────────────────────────────────────
    result = builder.build_site(record)

    return {
        'statusCode': 200 if result['ok'] else 500,
        'body': json.dumps({
            'site_url':      result['site_url'],
            'warnings':      result['warnings'],
            'warning_count': result['warning_count'],
        })
    }
