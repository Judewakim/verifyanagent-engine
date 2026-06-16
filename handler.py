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

    # ── 2. Extract the customer's email from the Stripe payload ───────────────
    session = stripe_event['data']['object']
    email = (session.get('customer_details') or {}).get('email', '').strip().lower()

    if not email:
        print("ERROR: No email found in Stripe payload.")
        return {'statusCode': 400, 'body': 'No customer email in Stripe payload'}

    print(f"Processing payment for: {email}")

    # ── 3. Find the matching Airtable form submission ─────────────────────────
    # Lambda connects Stripe payment → Airtable record using the email as the key.
    record = airtable_client.find_by_email(email)

    if not record:
        # Payment received but no form found — create an error record so
        # Airtable Automation 2 fires and emails Jude to investigate.
        print(f"No Airtable record found for: {email}")
        airtable_client.create_error_record(
            email,
            f"Payment received from {email} but no form submission found with this email. "
            "The client may have used a different email when filling the form. "
            "Please match manually and update this record."
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
