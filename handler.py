# handler.py
import json
import traceback

import stripe_verifier
import airtable_client
import s3_manager
import site_generator
import state_data
import cert_ocr


def _parse_license_numbers(text):
    """
    Parse the multi-line Airtable text format into a dict.

    Input format (one state per line):
        FL: W123456
        TX: 1234567

    Returns {'FL': 'W123456', 'TX': '1234567'}.
    """
    result = {}
    if not text:
        return result
    for line in text.splitlines():
        if ':' not in line:
            continue
        abbrev, number = line.split(':', 1)
        abbrev = abbrev.strip().upper()
        number = number.strip()
        if abbrev and number:
            result[abbrev] = number
    return result


def _format_license_numbers(d):
    """Format {'FL': 'W123456'} as multi-line text for writing back to Airtable."""
    return '\n'.join(f"{abbrev}: {num}" for abbrev, num in sorted(d.items()))


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

    # ── 6. OCR every uploaded cert to extract its state license number ───────
    # Every state card on the site displays its license number, so OCR runs on
    # every cert in cert_map regardless of whether the state's verify URL needs
    # the number. The manual override field always wins over OCR — that's how
    # Jude corrects misreads.
    print("Extracting license numbers from cert PDFs...")
    cert_map         = asset_map.get('certs', {})
    override_dict    = _parse_license_numbers(fields.get('license_numbers_override', ''))
    ocr_results      = {}

    for abbrev, _cert_path in cert_map.items():
        state_info = state_data.STATES.get(abbrev)
        if not state_info:
            continue   # unknown state code — skipped
        if abbrev in override_dict:
            continue   # manual override exists — skip OCR to save the API call
        try:
            pdf_bytes = s3_manager.download_cert(slug, abbrev)
            number    = cert_ocr.extract_license_number(
                pdf_bytes, abbrev, state_info['name']
            )
            if number:
                ocr_results[abbrev] = number
            else:
                errors.append(
                    f"OCR could not extract a license number for {abbrev} from the cert PDF. "
                    f"Add it manually to license_numbers_override in Airtable as '{abbrev}: <number>'."
                )
        except Exception as e:
            errors.append(f"OCR step failed for {abbrev}: {e}")

    # Merge: manual override wins over OCR
    license_numbers = {**ocr_results, **override_dict}
    print(f"License numbers resolved: {len(license_numbers)} total "
          f"({len(ocr_results)} OCR, {len(override_dict)} override)")

    # ── 7. Build state data for each state the agent is licensed in ───────────
    print("Building state license data...")
    agent_states = fields.get('states', [])   # list of state abbreviations from Airtable
    agent_npn    = str(fields.get('npn', ''))

    states_for_template = state_data.build_states_for_agent(
        agent_states, agent_npn, agent_name, cert_map, license_numbers, errors
    )
    print(f"Built data for {len(states_for_template)} states.")

    # ── 8. Generate the HTML ──────────────────────────────────────────────────
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

    # ── 9. Upload the site files to S3 ────────────────────────────────────────
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

    # ── 10. Update Airtable: build complete ───────────────────────────────────
    # Setting site_status = 'built' triggers Airtable Automation 2,
    # which emails Jude to go review the site.
    site_url    = f"https://{slug}.verifyanagent.com"
    build_notes = '\n'.join(errors) if errors else 'Build completed with no issues.'

    # Core status update — these fields are known-good and must succeed.
    airtable_client.update(record_id, {
        'site_status':  'built',
        'site_url':     site_url,
        'build_notes':  build_notes,
    })

    # Best-effort: write OCR results back to Airtable. A field-name or field-type
    # mismatch must NOT fail the whole build — the results are also in the logs above.
    try:
        airtable_client.update(record_id, {
            'license_numbers_ocr': _format_license_numbers(ocr_results),
        })
    except Exception as e:
        print(f"Could not write license_numbers_ocr "
              f"(verify the field exists and is type 'Long text'): {e}")

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