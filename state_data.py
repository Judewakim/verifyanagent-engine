# state_data.py
import re
import urllib.parse
from pathlib import Path

# Master database of all 50 states.
# seal filename must match EXACTLY what was uploaded to S3 assets/ folder.
#
# url is a template — placeholders supported: {NPN}, {LICENSE_NUM}, {FIRST_NAME}, {LAST_NAME}.
# A static URL with no placeholders is fine (lands the visitor on a search form).
# url=None means the verify button is not configured for this state yet (no button rendered).
# OCR auto-engages for any state whose url contains {LICENSE_NUM}.
STATES = {
    "AL": {"name": "Alabama",        "dept": "Dept. of Insurance",
           "seal": "alabama-seal.png",
           "url": "https://sbs.naic.org/solar-external-lookup/lookup/licensee/summary/{LICENSE_NUM}?jurisdiction=AL&entityType=IND&licenseType=PRO"},
    "AK": {"name": "Alaska",         "dept": "Division of Insurance",
           "seal": "alaska-seal.svg",        "url": None},
    "AZ": {"name": "Arizona",        "dept": "Dept. of Insurance and Financial Institutions",
           "seal": "arizona-seal.svg",       "url": None},
    "AR": {"name": "Arkansas",       "dept": "Insurance Dept.",
           "seal": "arkansas-seal.svg",
           "url": "https://external-lookup-web.prod.naic.org/lookup/licensee/summary/{LICENSE_NUM}?jurisdiction=AR&entityType=IND&licenseType=PRO"},
    "CA": {"name": "California",     "dept": "Dept. of Insurance",
           "seal": "california-seal.png",    "url": None},
    "CO": {"name": "Colorado",       "dept": "Division of Insurance",
           "seal": "colorado-seal.png",      "url": None},
    "CT": {"name": "Connecticut",    "dept": "Insurance Dept.",
           "seal": "connecticut-seal.png",   "url": None},
    "DE": {"name": "Delaware",       "dept": "Insurance Commissioner",
           "seal": "delaware-seal.png",      "url": None},
    "FL": {"name": "Florida",        "dept": "Dept. of Financial Services",
           "seal": "florida-seal.png",       "url": None},
    "GA": {"name": "Georgia",        "dept": "Insurance Commissioner",
           "seal": "georgia-seal.png",
           "url": "https://www.sircon.com/ComplianceExpress/Inquiry/consumerInquiry.do?nonSscrb=Y"},
    "HI": {"name": "Hawaii",         "dept": "Insurance Division",
           "seal": "hawaii-seal.png",        "url": None},
    "ID": {"name": "Idaho",          "dept": "Dept. of Insurance",
           "seal": "idaho-seal.png",         "url": None},
    "IL": {"name": "Illinois",       "dept": "Dept. of Insurance",
           "seal": "illinois-seal.png",      "url": None},
    "IN": {"name": "Indiana",        "dept": "Dept. of Insurance",
           "seal": "indiana-seal.png",       "url": None},
    "IA": {"name": "Iowa",           "dept": "Insurance Division",
           "seal": "iowa-seal.png",          "url": None},
    "KS": {"name": "Kansas",         "dept": "Insurance Dept.",
           "seal": "kansas-seal.png",        "url": None},
    "KY": {"name": "Kentucky",       "dept": "Insurance Commissioner",
           "seal": "kentucky-seal.png",      "url": None},
    "LA": {"name": "Louisiana",      "dept": "Dept. of Insurance",
           "seal": "louisiana-seal.png",
           "url": "https://www.ldi.la.gov/onlineservices/ProducerAdjusterSearch/Detail.aspx?LicenseType=Individual%20Producer&LicenseNumber={LICENSE_NUM}"},
    "ME": {"name": "Maine",          "dept": "Bureau of Insurance",
           "seal": "maine-seal.svg",         "url": None},
    "MD": {"name": "Maryland",       "dept": "Insurance Administration",
           "seal": "maryland-seal.svg",
           "url": "https://external-lookup-web.prod.naic.org/lookup/licensee/summary/{LICENSE_NUM}?jurisdiction=MD&entityType=IND&licenseType=PRO"},
    "MA": {"name": "Massachusetts",  "dept": "Division of Insurance",
           "seal": "massachusetts-seal.png", "url": None},
    "MI": {"name": "Michigan",       "dept": "Dept. of Insurance and Financial Services",
           "seal": "michigan-seal.png",
           "url": "https://difs.state.mi.us/Locators/?searchtype=InsAgent"},
    "MN": {"name": "Minnesota",      "dept": "Dept. of Commerce",
           "seal": "minnesota-seal.svg",     "url": None},
    "MS": {"name": "Mississippi",    "dept": "Insurance Dept.",
           "seal": "mississippi-seal.svg",   "url": None},
    "MO": {"name": "Missouri",       "dept": "Dept. of Commerce and Insurance",
           "seal": "missouri-seal.png",
           "url": "https://external-lookup-web.prod.naic.org/license-manager"},
    "MT": {"name": "Montana",        "dept": "Insurance Commissioner",
           "seal": "montana-seal.svg",       "url": None},
    "NE": {"name": "Nebraska",       "dept": "Dept. of Insurance",
           "seal": "nebraska-seal.png",      "url": None},
    "NV": {"name": "Nevada",         "dept": "Division of Insurance",
           "seal": "nevada-seal.svg",        "url": None},
    "NH": {"name": "New Hampshire",  "dept": "Insurance Dept.",
           "seal": "newHampshire-seal.png",  "url": None},
    "NJ": {"name": "New Jersey",     "dept": "Dept. of Banking and Insurance",
           "seal": "newJersey-seal.png",     "url": None},
    "NM": {"name": "New Mexico",     "dept": "Office of Superintendent of Insurance",
           "seal": "newMexico-seal.png",     "url": None},
    "NY": {"name": "New York",       "dept": "Dept. of Financial Services",
           "seal": "newYork-seal.png",       "url": None},
    "NC": {"name": "North Carolina", "dept": "Dept. of Insurance",
           "seal": "northCarolina-seal.svg", "url": None},
    "ND": {"name": "North Dakota",   "dept": "Insurance Dept.",
           "seal": "northDakota-seal.png",   "url": None},
    "OH": {"name": "Ohio",           "dept": "Dept. of Insurance",
           "seal": "ohio-seal.png",          "url": None},
    "OK": {"name": "Oklahoma",       "dept": "Insurance Dept.",
           "seal": "oklahoma-seal.svg",
           "url": "https://sbs.naic.org/solar-external-lookup/lookup/licensee/summary/{LICENSE_NUM}?jurisdiction=OK&entityType=IND&licenseType=PRO"},
    "OR": {"name": "Oregon",         "dept": "Insurance Division",
           "seal": "oregon-seal.svg",        "url": None},
    "PA": {"name": "Pennsylvania",   "dept": "Insurance Dept.",
           "seal": "pennsylvania-seal.png",  "url": None},
    "RI": {"name": "Rhode Island",   "dept": "Insurance Division",
           "seal": "rhodeIsland-seal.png",   "url": None},
    "SC": {"name": "South Carolina", "dept": "Dept. of Insurance",
           "seal": "southCarolina-seal.svg",
           "url": "https://sbs.naic.org/solar-external-lookup/lookup/licensee/summary/{NPN}?jurisdiction=SC&entityType=IND&licenseType=PRO"},
    "SD": {"name": "South Dakota",   "dept": "Division of Insurance",
           "seal": "southDakota-seal.svg",   "url": None},
    "TN": {"name": "Tennessee",      "dept": "Dept. of Commerce and Insurance",
           "seal": "tennessee-seal.svg",
           "url": "https://external-lookup-web.prod.naic.org/lookup/licensee/summary/{LICENSE_NUM}?jurisdiction=TN&entityType=IND&licenseType=PRO"},
    "TX": {"name": "Texas",          "dept": "Dept. of Insurance",
           "seal": "texas-seal.png",
           "url": "https://www.sircon.com/ComplianceExpress/Inquiry/consumerInquiry.do?nonSscrb=Y"},
    "UT": {"name": "Utah",           "dept": "Insurance Dept.",
           "seal": "utah-seal.png",          "url": None},
    "VT": {"name": "Vermont",        "dept": "Dept. of Financial Regulation",
           "seal": "vermont-seal.png",       "url": None},
    "VA": {"name": "Virginia",       "dept": "Bureau of Insurance",
           "seal": "virginia-seal.png",
           "url": "https://www.scc.virginia.gov/boi/consumerinquiry/Search.aspx?searchType=agent"},
    "WA": {"name": "Washington",     "dept": "Office of the Insurance Commissioner",
           "seal": "washington-seal.png",    "url": None},
    "WV": {"name": "West Virginia",  "dept": "Insurance Commissioner",
           "seal": "westVirginia-seal.png",  "url": None},
    "WI": {"name": "Wisconsin",      "dept": "Office of the Commissioner of Insurance",
           "seal": "wisconsin-seal.svg",
           "url": "https://sbs.naic.org/solar-external-lookup/lookup/licensee/summary/{NPN}?jurisdiction=WI&entityType=IND&licenseType=INT"},
    "WY": {"name": "Wyoming",        "dept": "Insurance Dept.",
           "seal": "wyoming-seal.png",       "url": None},
}


_PLACEHOLDER_RE = re.compile(r'\{([A-Z_]+)\}')

# Friendly messages for placeholders that can't be filled — surfaced in build_notes.
_MISSING_REASON = {
    'LICENSE_NUM': "OCR could not extract a license number — add it to license_numbers_override in Airtable as '{abbrev}: <number>'",
    'NPN':         "no NPN on the agent record",
    'FIRST_NAME':  "agent name is empty (need a first name)",
    'LAST_NAME':   "agent name is single-token (need a last name)",
}


def build_states_for_agent(selected_states, npn, agent_name, cert_map, license_numbers, errors):
    """
    Takes the list of states the agent is licensed in (from Airtable)
    and builds the data each state card in the HTML template needs.

    selected_states:  list like ['FL', 'SC', 'TX']
    npn:              the agent's NPN string e.g. '22168646'
    agent_name:       the agent's full name (split into first/last for URL substitution)
    cert_map:         dict of uploaded certs e.g. {'FL': 'certs/FL.pdf', 'SC': 'certs/SC.pdf'}
    license_numbers:  dict of state-specific license numbers e.g. {'AL': '3004167047'}
                      (from OCR + manual override; only consulted for states whose URL
                      template contains {LICENSE_NUM})
    errors:           list to append warnings to (doesn't stop the build)

    Returns a list of dicts, one per state, ready to be passed to the Jinja2 template.
    """
    parts = (agent_name or '').split()
    first_name = parts[0] if parts else ''
    last_name  = ' '.join(parts[1:]) if len(parts) > 1 else ''

    result = []

    for abbrev in selected_states:
        abbrev = abbrev.strip().upper()
        state_info = STATES.get(abbrev)

        if not state_info:
            errors.append(f"Unknown state code '{abbrev}' in agent's states list — skipped.")
            continue

        verify_url = _build_verify_url(
            abbrev, state_info, npn, first_name, last_name, license_numbers, errors
        )

        # Check whether a certificate was uploaded for this state
        cert_url = cert_map.get(abbrev)
        if not cert_url:
            errors.append(
                f"{state_info['name']} ({abbrev}): No certificate PDF found "
                f"(expected a file named '{abbrev}.pdf'). "
                f"'View Certificate' button will show 'Certificate Pending'."
            )

        result.append({
            'name':           state_info['name'],
            'abbrev':         abbrev,
            'dept':           state_info['dept'],
            'seal_filename':  state_info['seal'],
            'npn':            npn,
            'license_number': license_numbers.get(abbrev),   # None if missing — template falls back to em-dash
            'verify_url':     verify_url,   # None if can't be built / state not configured
            'cert_url':       cert_url,     # None if cert wasn't uploaded
        })

    return result


def _build_verify_url(abbrev, state_info, npn, first_name, last_name, license_numbers, errors):
    """Substitute placeholders in the state's URL template, or return None + warn."""
    url_template = state_info.get('url')
    if not url_template:
        # State intentionally not configured yet — no button, no warning.
        return None

    subs = {
        'NPN':         str(npn or ''),
        'FIRST_NAME':  first_name,
        'LAST_NAME':   last_name,
        'LICENSE_NUM': str(license_numbers.get(abbrev) or ''),
    }

    placeholders = set(_PLACEHOLDER_RE.findall(url_template))
    missing = [p for p in placeholders if not subs.get(p)]
    if missing:
        reasons = '; '.join(
            _MISSING_REASON.get(p, p).format(abbrev=abbrev) for p in missing
        )
        errors.append(
            f"{state_info['name']} ({abbrev}): 'Verify License' button disabled — "
            f"missing {', '.join(missing)} ({reasons})."
        )
        return None

    verify_url = url_template
    for key in placeholders:
        verify_url = verify_url.replace(
            '{' + key + '}', urllib.parse.quote(subs[key], safe='')
        )
    return verify_url


def match_state_from_filename(filename):
    """
    Maps a certificate filename to a state abbreviation using 3-tier matching.
    Returns the abbreviation string (e.g. 'FL') or None if no confident match.

    Tier 1 — full state name found anywhere in the filename (perfect match)
    Tier 2 — state abbreviation found as a complete token, e.g. 'FL' in 'FL-cert.pdf'
    Tier 3 — majority prefix (≥60%, min 4 chars) of state name at start of filename

    States are checked longest-name-first so superstrings win:
    'westvirginia' matches WV before 'virginia' can match VA.
    """
    stem = Path(filename).stem.lower()
    alpha_only = re.sub(r'[^a-z]', '', stem)
    tokens = [t for t in re.split(r'[^a-z]+', stem) if t]

    sorted_states = sorted(STATES.items(), key=lambda x: len(x[1]['name']), reverse=True)

    # Tier 1: full state name (spaces/hyphens stripped) appears anywhere in filename
    for abbrev, info in sorted_states:
        name_clean = re.sub(r'[^a-z]', '', info['name'].lower())
        if name_clean in alpha_only:
            return abbrev

    # Tier 2: abbreviation is a complete token (guards against 'in' matching 'invoice', etc.)
    tier2 = [abbrev for abbrev, _ in STATES.items() if abbrev.lower() in tokens]
    if len(tier2) == 1:
        return tier2[0]
    if len(tier2) > 1:
        return None  # ambiguous — multiple states' abbreviations in one filename

    # Tier 3: majority prefix at the start of filename (states with names > 5 chars only)
    for abbrev, info in sorted_states:
        name_clean = re.sub(r'[^a-z]', '', info['name'].lower())
        if len(name_clean) <= 5:
            continue
        prefix = name_clean[:max(4, int(len(name_clean) * 0.6))]
        if alpha_only.startswith(prefix):
            return abbrev

    return None
