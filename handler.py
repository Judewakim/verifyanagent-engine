# handler.py
import json
import traceback

import stripe_verifier
import airtable_client
import s3_manager
import site_generator
import state_data


def handler(event, context):
    """
    AWS Lambda entry point.
    Called by API Gateway every time Stripe sends a webhook.
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

    record_id = record['id']
    fields = record['fields']
    agent_name = fields.get('name', 'Unknown Agent')
    print(f"Found Airtable record for: {agent_name} (record ID: {record_id})")

    # Generate the URL-safe slug (used for S3 folder and subdomain)
    slug = s3_manager.slugify(agent_name)
    print(f"Agent slug: {slug} → site will be at https://{slug}.verifyanagent.com")

    # Accumulate non-fatal warnings here throughout the build
    errors = []

    # ── 4. Update Airtable: payment confirmed, build starting ─────────────────
    airtable_client.update(record_id, {
        'payment_status': 'paid',
        'site_status':    'building',
    })
    print("Airtable updated: payment_status=paid, site_status=building")

    # ── 5. Download agent assets from Airtable CDN → upload to S3 ────────────
    print("Downloading and uploading agent assets...")
    try:
        asset_map = s3_manager.upload_assets(record, slug, errors)
        print(f"Assets done. Warnings so far: {len(errors)}")
    except Exception:
        # Something catastrophic happened (e.g. S3 permissions error)
        err = traceback.format_exc()
        errors.append(f"CRITICAL: Asset upload failed entirely:\n{err}")
        asset_map = {'certs': {}}  # continue with empty assets

    # ── 6. Build state data for each state the agent is licensed in ───────────
    print("Building state license data...")
    agent_states = fields.get('states', [])   # list of state abbreviations from Airtable
    agent_npn    = str(fields.get('npn', ''))
    cert_map     = asset_map.get('certs', {})

    states_for_template = state_data.build_states_for_agent(
        agent_states, agent_npn, cert_map, errors
    )
    print(f"Built data for {len(states_for_template)} states.")

    # ── 7. Generate the HTML ──────────────────────────────────────────────────
    print("Rendering HTML template...")
    try:
        html = site_generator.render(record, slug, asset_map, states_for_template)
        print("HTML rendered successfully.")
    except Exception:
        # If template rendering fails, we can't continue — update Airtable and stop.
        err = traceback.format_exc()
        print(f"HTML rendering FAILED:\n{err}")
        airtable_client.update(record_id, {
            'site_status':  'error',
            'build_notes':  f"HTML generation failed:\n{err}\n\nOther warnings:\n" + '\n'.join(errors),
        })
        return {'statusCode': 500, 'body': 'HTML generation failed'}

    # ── 8. Upload the site files to S3 ────────────────────────────────────────
    print("Uploading site files to S3...")
    try:
        s3_manager.upload_site_files(slug, html)
        print("Site files uploaded.")
    except Exception:
        err = traceback.format_exc()
        print(f"Site upload FAILED:\n{err}")
        airtable_client.update(record_id, {
            'site_status':  'error',
            'build_notes':  f"S3 site upload failed:\n{err}\n\nOther warnings:\n" + '\n'.join(errors),
        })
        return {'statusCode': 500, 'body': 'Site upload failed'}

    # ── 9. Update Airtable: build complete ────────────────────────────────────
    # Setting site_status = 'built' triggers Airtable Automation 2,
    # which emails Jude to go review the site.
    site_url    = f"https://{slug}.verifyanagent.com"
    build_notes = '\n'.join(errors) if errors else 'Build completed with no issues.'

    airtable_client.update(record_id, {
        'site_status':  'built',
        'site_url':     site_url,
        'build_notes':  build_notes,
    })

    print(f"=== BUILD COMPLETE ===")
    print(f"Site URL: {site_url}")
    print(f"Build notes:\n{build_notes}")

    return {
        'statusCode': 200,
        'body': json.dumps({
            'site_url':    site_url,
            'warnings':    errors,
            'warning_count': len(errors),
        })
    }