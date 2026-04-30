# site_generator.py
import os
from pathlib import Path
from jinja2 import Environment, FileSystemLoader

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

    # The primary color might be entered as '#1a3a5c' or '1a3a5c' — normalize it
    raw_color = fields.get('primary_color', '#1a3a5c').strip()
    primary_color = raw_color if raw_color.startswith('#') else f'#{raw_color}'

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
        'primary_color': primary_color,
        'calendly_url':  fields.get('calendly_url', ''),

        # File references (relative URLs — files are in the same S3 folder as index.html)
        'profile_pic':   asset_map.get('profile_pic') or 'profile.jpg',
        'logo_full':     asset_map.get('logo_full') or 'logo-full.png',
        'logo_icon':     asset_map.get('logo_icon') or asset_map.get('logo_full') or 'logo-full.png',
        'carriers_img':  asset_map.get('carriers_img'),   # None = don't show the section

        # License cards (list of state dicts)
        'states': states,

        # Footer
        'year': '2026',
        'site_url': f'https://{slug}.verifyanagent.com',
    }

    return template.render(**context)