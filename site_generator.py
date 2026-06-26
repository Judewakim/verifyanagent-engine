# site_generator.py
import os
from pathlib import Path
from jinja2 import Environment, FileSystemLoader


def _contrast_text_color(hex_color):
    """
    Picks a readable text color (black or white) to sit on top of a brand-color
    fill — used for the button-hover text so light brand colors stay legible.

    Returns '#111111' for light backgrounds, '#ffffff' for dark ones.
    Falls back to white if the hex can't be parsed.

    Uses the standard sRGB relative-luminance formula (WCAG) with a 0.5 cut.
    """
    h = hex_color.lstrip('#').strip()
    if len(h) == 3:                      # expand shorthand e.g. 'abc' -> 'aabbcc'
        h = ''.join(c * 2 for c in h)
    if len(h) != 6:
        return '#ffffff'
    try:
        r, g, b = (int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    except ValueError:
        return '#ffffff'

    # Linearize each channel, then weight by perceived brightness.
    def _lin(c):
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    luminance = 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)
    return '#111111' if luminance > 0.5 else '#ffffff'


def render(record, slug, asset_map, states):
    """
    Renders the Jinja2 HTML template with this agent's data.

    record:    full Airtable record dict (has 'id' and 'fields')
    slug:      URL-safe version of agent name e.g. 'john-smith'
    asset_map: dict of uploaded file S3 paths from s3_manager.upload_assets()
    states:    list of state dicts from state_data.build_states_for_agent()

    Returns the complete HTML as a Python string.
    """
    fields = record['fields']

    # Find the templates/ folder (it's in the same directory as this file)
    templates_dir = str(Path(__file__).parent / 'templates')
    env = Environment(loader=FileSystemLoader(templates_dir))
    template = env.get_template('index.html.j2')

    # The primary color might be entered as '#1a3a5c' or '1a3a5c' — normalize it.
    # If the field is blank, leave primary_color empty ('') so the template
    # falls back to the monochrome black/white button treatment.
    raw_color = fields.get('primary_color', '').strip()
    if raw_color:
        primary_color = raw_color if raw_color.startswith('#') else f'#{raw_color}'
        # Black or white text for the button-hover fill, based on the brand
        # color's luminance — keeps text legible on light brand colors.
        brand_text_color = _contrast_text_color(primary_color)
    else:
        primary_color = ''
        brand_text_color = ''

    # Build the full context dict — everything the template can access
    context = {
        # Agent identity
        'agent_name':    fields.get('name', 'Agent'),
        'agency_name':   fields.get('agency_name', fields.get('name', 'Insurance Agency')),
        'agent_email':   fields.get('email', ''),
        'agent_npn':     str(fields.get('npn', '')),
        'agent_bio':     fields.get('bio', ''),
        'agent_slug':    slug,

        # Branding
        'primary_color':    primary_color,
        'brand_text_color': brand_text_color,
        'calendly_url':     fields.get('calendly_url', ''),

        # File references (relative URLs — files are in the same S3 folder as index.html)
        'profile_pic':   asset_map.get('profile_pic') or 'profile.jpg',
        'logo_full':     asset_map.get('logo_full') or asset_map.get('logo_icon') or 'logo-full.png',
        'logo_icon':     asset_map.get('logo_icon') or asset_map.get('logo_full') or 'logo-full.png',
        'carriers_img':  asset_map.get('carriers_img'),   # None = don't show the section

        # License cards (list of state dicts)
        'states': states,

        # When True, suppress every "View Certificate" button (per-client opt-in).
        # Airtable omits unchecked checkboxes, so absent == not hidden == show certs.
        'hide_certificates': bool(fields.get('hide_certificates', False)),

        # Footer
        'year': '2026',
        'site_url': f'https://{slug}.verifyanagent.com',
    }

    return template.render(**context)