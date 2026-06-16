# builder.py — the reusable site-build pipeline.
#
# This is the heart of the system: given a full Airtable record, it downloads
# assets, OCRs certs, builds the per-state license cards, renders the HTML, and
# uploads the finished site to S3. Both entry points share it:
#   - handler.py        (the Stripe webhook — runs on payment)
#   - admin_api.py      (the admin "Publish" button — runs on demand)
#
# Keeping the build here (instead of inside handler.py) means the admin tool can
# republish an agent's site by calling build_site() directly, with no need to
# synthesize a fake Stripe webhook.
import traceback

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


def _parse_verify_urls(text):
    """
    Parse the multi-line verify_url_override field into a dict.

    Input format (one state per line) — the value is an EXACT, manually-retrieved
    licensee URL (used for states like Florida whose verify URLs are randomized
    and can't be built from a template):
        FL: https://licenseesearch.fldfs.com/Licensee/<unique-id>

    Note: split on the FIRST colon only — the URL itself contains colons. Only the
    state abbreviation is upper-cased; the URL is preserved verbatim.

    Returns {'FL': 'https://...'}.
    """
    result = {}
    if not text:
        return result
    for line in text.splitlines():
        if ':' not in line:
            continue
        abbrev, url = line.split(':', 1)
        abbrev = abbrev.strip().upper()
        url = url.strip()
        if abbrev and url:
            result[abbrev] = url
    return result


def build_site(record, *, update_status=True):
    """
    Run the full build for one agent and upload the site to S3.

    record:        full Airtable record dict (has 'id' and 'fields')
    update_status: when True (default), write payment/site status back to Airtable
                   as the build progresses. Both current callers want this.

    Returns a result dict:
        {
            'ok':            bool,    # False if the build failed (HTML/upload error)
            'slug':          str,
            'site_url':      str,
            'warnings':      [str],   # non-fatal build notes
            'warning_count': int,
            'license_numbers': {abbrev: number},
        }
    Catastrophic failures (HTML render / S3 upload) set site_status='error' in
    Airtable (when update_status) and return ok=False — they do NOT raise.
    """
    record_id  = record['id']
    fields     = record['fields']
    agent_name = fields.get('name', 'Unknown Agent')
    slug       = s3_manager.slugify(agent_name)
    site_url   = f"https://{slug}.verifyanagent.com"
    print(f"Building site for: {agent_name} (record {record_id}) → {site_url}")

    # Accumulate non-fatal warnings here throughout the build
    errors = []
    # Resolved below; initialized here so _result() can reference it on early return.
    license_numbers = {}

    def _result(ok):
        return {
            'ok':              ok,
            'slug':            slug,
            'site_url':        site_url,
            'warnings':        errors,
            'warning_count':   len(errors),
            'license_numbers': license_numbers,
        }

    # ── 1. Mark the build as started ─────────────────────────────────────────
    if update_status:
        airtable_client.update(record_id, {
            'payment_status': 'paid',
            'site_status':    'building',
        })
        print("Airtable updated: payment_status=paid, site_status=building")

    # ── 2. Download agent assets from Airtable CDN → upload to S3 ────────────
    print("Downloading and uploading agent assets...")
    try:
        asset_map = s3_manager.upload_assets(record, slug, errors)
        print(f"Assets done. Warnings so far: {len(errors)}")
    except Exception:
        err = traceback.format_exc()
        errors.append(f"CRITICAL: Asset upload failed entirely:\n{err}")
        asset_map = {'certs': {}}  # continue with empty assets

    # ── 3. OCR every uploaded cert to extract its state license number ───────
    # Every state card displays its license number, so OCR runs on every cert.
    # The manual override always wins over OCR — that's how Jude corrects misreads.
    print("Extracting license numbers from cert PDFs...")
    cert_map      = asset_map.get('certs', {})
    override_dict = _parse_license_numbers(fields.get('license_numbers_override', ''))
    ocr_results   = {}

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

    # ── 4. Build state data for each state the agent is licensed in ───────────
    print("Building state license data...")
    agent_states         = fields.get('states', [])   # list of state abbreviations
    agent_npn            = str(fields.get('npn', ''))
    verify_url_overrides = _parse_verify_urls(fields.get('verify_url_override', ''))

    states_for_template = state_data.build_states_for_agent(
        agent_states, agent_npn, agent_name, cert_map, license_numbers, errors,
        verify_url_override=verify_url_overrides,
    )
    print(f"Built data for {len(states_for_template)} states.")

    # ── 5. Generate the HTML ──────────────────────────────────────────────────
    print("Rendering HTML template...")
    try:
        html = site_generator.render(record, slug, asset_map, states_for_template)
        print("HTML rendered successfully.")
    except Exception:
        err = traceback.format_exc()
        print(f"HTML rendering FAILED:\n{err}")
        if update_status:
            airtable_client.update(record_id, {
                'site_status': 'error',
                'build_notes': f"HTML generation failed:\n{err}\n\nOther warnings:\n" + '\n'.join(errors),
            })
        errors.append(f"HTML generation failed:\n{err}")
        return _result(False)

    # ── 6. Upload the site files to S3 ────────────────────────────────────────
    print("Uploading site files to S3...")
    try:
        s3_manager.upload_site_files(slug, html)
        print("Site files uploaded.")
    except Exception:
        err = traceback.format_exc()
        print(f"Site upload FAILED:\n{err}")
        if update_status:
            airtable_client.update(record_id, {
                'site_status': 'error',
                'build_notes': f"S3 site upload failed:\n{err}\n\nOther warnings:\n" + '\n'.join(errors),
            })
        errors.append(f"S3 site upload failed:\n{err}")
        return _result(False)

    # ── 7. Mark the build complete ────────────────────────────────────────────
    # The S3 origin is uncached, so the upload above is already live — no CDN
    # invalidation step (it would cost money for no benefit).
    build_notes = '\n'.join(errors) if errors else 'Build completed with no issues.'

    if update_status:
        # Core status update — these fields are known-good and must succeed.
        airtable_client.update(record_id, {
            'site_status': 'built',
            'site_url':    site_url,
            'build_notes': build_notes,
        })

        # Best-effort: write OCR results back. A field-name/type mismatch must NOT
        # fail the whole build — the results are also in the logs above.
        try:
            airtable_client.update(record_id, {
                'license_numbers_ocr': _format_license_numbers(ocr_results),
            })
        except Exception as e:
            print(f"Could not write license_numbers_ocr "
                  f"(verify the field exists and is type 'Long text'): {e}")

    print(f"=== BUILD COMPLETE ===\nSite URL: {site_url}\nBuild notes:\n{build_notes}")
    return _result(True)
