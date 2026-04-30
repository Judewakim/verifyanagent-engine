# s3_manager.py
import os
import re
import boto3
import requests
from pathlib import Path
import state_data

# Create the S3 client once (reused across all uploads in a single Lambda invocation)
s3 = boto3.client('s3')

def slugify(name):
    """
    Converts a person's name into a URL-safe string used as their subdomain.
    Examples:
        'John Smith'     → 'john-smith'
        'María García'   → 'mara-garca'  (special chars removed)
        'O\'Brien, Tom'  → 'obrien-tom'
    """
    name = name.lower().strip()
    name = re.sub(r"[^a-z0-9\s-]", "", name)   # remove everything except letters, numbers, spaces, hyphens
    name = re.sub(r"\s+", "", name)             # spaces gets removed
    name = re.sub(r"-+", "-", name)              # collapse multiple hyphens into one
    return name.strip("-")                        # remove leading/trailing hyphens

def _guess_content_type(filename):
    """
    Returns the correct MIME type for a file based on its extension.
    This tells browsers how to handle the file (display image vs. download PDF, etc.)
    """
    ext = Path(filename).suffix.lower()
    mapping = {
        ".jpg":  "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png":  "image/png",
        ".gif":  "image/gif",
        ".svg":  "image/svg+xml",
        ".webp": "image/webp",
        ".pdf":  "application/pdf",
        ".css":  "text/css",
        ".js":   "application/javascript",
        ".html": "text/html; charset=utf-8",
    }
    return mapping.get(ext, "application/octet-stream")

def _download(url):
    """
    Downloads a file from a URL and returns its raw bytes.
    The 30-second timeout prevents Lambda from hanging forever if a URL is slow.
    """
    response = requests.get(url, timeout=30)
    response.raise_for_status()  # raises an exception if download failed (404, 403, etc.)
    return response.content      # raw bytes

def _upload_to_s3(s3_key, content_bytes, content_type):
    """
    Uploads raw bytes to S3 at the given key (path).
    s3_key example: 'agents/john-smith/profile.jpg'
    """
    bucket = os.environ['S3_BUCKET']
    s3.put_object(
        Bucket=bucket,
        Key=s3_key,
        Body=content_bytes,
        ContentType=content_type
    )

def upload_assets(record, slug, errors):
    """
    Downloads every file attachment from the agent's Airtable record
    and uploads each one to S3 under agents/{slug}/.

    Returns a dict called asset_map:
    {
        'profile_pic': 'profile.jpg',       ← relative URL the HTML template will use
        'logo_full':   'logo-full.png',
        'logo_icon':   'logo-icon.png',     ← falls back to logo_full if not uploaded
        'carriers_img':'carriers.jpg',
        'certs': {                           ← dict of state abbrev → relative cert path
            'FL': 'certs/FL.pdf',
            'TX': 'certs/TX.pdf',
        }
    }
    Errors are appended to the 'errors' list but don't stop the build.
    """
    fields = record['fields']
    asset_map = {}

    # ── Helper: download one attachment and upload to S3 ─────────────────────
    def process_attachment(attachments, field_label, s3_filename_base):
        """
        Downloads the first attachment in the list and uploads it to S3.
        Returns the filename used (e.g. 'profile.jpg') or None on failure.
        """
        if not attachments:
            errors.append(f"No {field_label} uploaded — field was empty.")
            return None
        attachment = attachments[0]
        original_name = attachment.get('filename', 'file')
        ext = Path(original_name).suffix.lower() or '.jpg'
        filename = f"{s3_filename_base}{ext}"
        try:
            content = _download(attachment['url'])
            _upload_to_s3(f"agents/{slug}/{filename}", content, _guess_content_type(filename))
            print(f"  Uploaded {field_label}: agents/{slug}/{filename}")
            return filename
        except Exception as e:
            errors.append(f"Failed to download/upload {field_label}: {e}")
            return None

    # ── Profile picture ────────────────────────────────────────────────────────
    asset_map['profile_pic'] = process_attachment(
        fields.get('profile_pic', []), 'profile picture', 'profile'
    )

    # ── Logo (full) ────────────────────────────────────────────────────────────
    asset_map['logo_full'] = process_attachment(
        fields.get('logo_full', []), 'full logo', 'logo-full'
    )

    # ── Logo (icon) — optional, falls back to full logo ───────────────────────
    logo_icon = process_attachment(
        fields.get('logo_icon', []), 'logo icon', 'logo-icon'
    )
    # If no icon was uploaded, use the full logo as the icon (same file, different reference)
    asset_map['logo_icon'] = logo_icon or asset_map.get('logo_full')

    # ── Carriers image ─────────────────────────────────────────────────────────
    asset_map['carriers_img'] = process_attachment(
        fields.get('carriers_img', []), 'carriers image', 'carriers'
    )

    # ── Certificate PDFs ───────────────────────────────────────────────────────
    # Airtable returns cert_uploads as a list of attachment objects.
    # Each should be named like 'FL.pdf', 'TX.pdf', etc. (the agent was instructed to name them this way).
    cert_map = {}   # { 'FL': 'certs/FL.pdf', 'TX': 'certs/TX.pdf', ... }
    cert_attachments = fields.get('cert_uploads', [])

    if not cert_attachments:
        errors.append("No certificate PDFs uploaded at all.")
    else:
        for cert in cert_attachments:
            original_name = cert.get('filename', '')
            abbrev = state_data.match_state_from_filename(original_name)

            if abbrev is None:
                errors.append(
                    f"Certificate file '{original_name}' could not be matched to any US state — "
                    f"skipping. Rename it to include the state name or abbreviation "
                    f"(e.g. 'FL.pdf', 'florida-cert.pdf')."
                )
                continue

            try:
                content = _download(cert['url'])
                s3_key = f"agents/{slug}/certs/{abbrev}.pdf"
                _upload_to_s3(s3_key, content, "application/pdf")
                cert_map[abbrev] = f"certs/{abbrev}.pdf"
                print(f"  Uploaded cert: {s3_key}  (matched from '{original_name}')")
            except Exception as e:
                errors.append(f"Failed to download/upload certificate for {abbrev}: {e}")

    asset_map['certs'] = cert_map
    return asset_map


def upload_site_files(slug, html_content):
    """
    Uploads the three files that make up the agent's website to S3:
    1. index.html — the generated HTML (passed in as a string)
    2. style.css  — the visual stylesheet (bundled in the Lambda package)
    3. script.js  — the interactivity code (bundled in the Lambda package)

    'Bundled in the Lambda package' means these files are uploaded WITH the Lambda code
    at deploy time — they live inside the Lambda function itself, not downloaded at runtime.
    """
    bucket = os.environ['S3_BUCKET']

    # Upload the generated HTML string
    s3.put_object(
        Bucket=bucket,
        Key=f"agents/{slug}/index.html",
        Body=html_content.encode('utf-8'),
        ContentType="text/html; charset=utf-8"
    )
    print(f"  Uploaded: agents/{slug}/index.html")

    # Upload CSS and JS from the Lambda package's templates/ folder
    templates_dir = Path(__file__).parent / "templates"
    for filename, content_type in [
        ("style.css", "text/css"),
        ("script.js", "application/javascript"),
    ]:
        filepath = templates_dir / filename
        with open(filepath, "rb") as f:
            s3.put_object(
                Bucket=bucket,
                Key=f"agents/{slug}/{filename}",
                Body=f.read(),
                ContentType=content_type
            )
        print(f"  Uploaded: agents/{slug}/{filename}")