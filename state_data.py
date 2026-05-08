# state_data.py
import re
from pathlib import Path

# Master database of all 50 states.
# seal filename must match EXACTLY what was uploaded to S3 assets/ folder.
STATES = {
    "AL": {"name": "Alabama",        "dept": "Dept. of Insurance",
           "seal": "alabama-seal.png",       "type": "manual",       "url": None},
    "AK": {"name": "Alaska",         "dept": "Division of Insurance",
           "seal": "alaska-seal.svg",        "type": "manual",       "url": None},
    "AZ": {"name": "Arizona",        "dept": "Dept. of Insurance and Financial Institutions",
           "seal": "arizona-seal.png",       "type": "manual",       "url": None},
    "AR": {"name": "Arkansas",       "dept": "Insurance Dept.",
           "seal": "arkansas-seal.png",      "type": "manual",       "url": None},
    "CA": {"name": "California",     "dept": "Dept. of Insurance",
           "seal": "california-seal.png",    "type": "manual",       "url": None},
    "CO": {"name": "Colorado",       "dept": "Division of Insurance",
           "seal": "colorado-seal.png",      "type": "manual",       "url": None},
    "CT": {"name": "Connecticut",    "dept": "Insurance Dept.",
           "seal": "connecticut-seal.png",   "type": "manual",       "url": None},
    "DE": {"name": "Delaware",       "dept": "Insurance Commissioner",
           "seal": "delaware-seal.png",      "type": "manual",       "url": None},
    "FL": {"name": "Florida",        "dept": "Dept. of Financial Services",
           "seal": "florida-seal.png",       "type": "license_num",
           "url": "https://licenseesearch.fldfs.com/Licensee/{LICENSE_NUM}"},
    "GA": {"name": "Georgia",        "dept": "Insurance Commissioner",
           "seal": "georgia-seal.png",       "type": "manual",       "url": None},
    "HI": {"name": "Hawaii",         "dept": "Insurance Division",
           "seal": "hawaii-seal.png",        "type": "manual",       "url": None},
    "ID": {"name": "Idaho",          "dept": "Dept. of Insurance",
           "seal": "idaho-seal.png",         "type": "manual",       "url": None},
    "IL": {"name": "Illinois",       "dept": "Dept. of Insurance",
           "seal": "illinois-seal.png",      "type": "manual",       "url": None},
    "IN": {"name": "Indiana",        "dept": "Dept. of Insurance",
           "seal": "indiana-seal.png",       "type": "manual",       "url": None},
    "IA": {"name": "Iowa",           "dept": "Insurance Division",
           "seal": "iowa-seal.png",          "type": "manual",       "url": None},
    "KS": {"name": "Kansas",         "dept": "Insurance Dept.",
           "seal": "kansas-seal.png",        "type": "manual",       "url": None},
    "KY": {"name": "Kentucky",       "dept": "Insurance Commissioner",
           "seal": "kentucky-seal.png",      "type": "manual",       "url": None},
    "LA": {"name": "Louisiana",      "dept": "Dept. of Insurance",
           "seal": "louisiana-seal.png",     "type": "license_num",
           "url": "https://www.ldi.la.gov/onlineservices/ProducerAdjusterSearch/Detail.aspx?LicenseType=Individual%20Producer&LicenseNumber={LICENSE_NUM}"},
    "ME": {"name": "Maine",          "dept": "Bureau of Insurance",
           "seal": "maine-seal.png",         "type": "manual",       "url": None},
    "MD": {"name": "Maryland",       "dept": "Insurance Administration",
           "seal": "maryland-seal.png",      "type": "manual",       "url": None},
    "MA": {"name": "Massachusetts",  "dept": "Division of Insurance",
           "seal": "massachusetts-seal.png", "type": "manual",       "url": None},
    "MI": {"name": "Michigan",       "dept": "Dept. of Insurance and Financial Services",
           "seal": "michigan-seal.png",      "type": "manual",       "url": None},
    "MN": {"name": "Minnesota",      "dept": "Dept. of Commerce",
           "seal": "minnesota-seal.svg",     "type": "manual",       "url": None},
    "MS": {"name": "Mississippi",    "dept": "Insurance Dept.",
           "seal": "mississippi-seal.png",   "type": "manual",       "url": None},
    "MO": {"name": "Missouri",       "dept": "Dept. of Commerce and Insurance",
           "seal": "missouri-seal.png",      "type": "license_num",
           "url": "https://external-lookup-web.prod.naic.org/license-manager/summary/{LICENSE_NUM}?jurisdiction=MO&entityType=IND"},
    "MT": {"name": "Montana",        "dept": "Insurance Commissioner",
           "seal": "montana-seal.svg",       "type": "manual",       "url": None},
    "NE": {"name": "Nebraska",       "dept": "Dept. of Insurance",
           "seal": "nebraska-seal.png",      "type": "manual",       "url": None},
    "NV": {"name": "Nevada",         "dept": "Division of Insurance",
           "seal": "nevada-seal.svg",        "type": "manual",       "url": None},
    "NH": {"name": "New Hampshire",  "dept": "Insurance Dept.",
           "seal": "newHampshire-seal.png",  "type": "manual",       "url": None},
    "NJ": {"name": "New Jersey",     "dept": "Dept. of Banking and Insurance",
           "seal": "newJersey-seal.png",     "type": "manual",       "url": None},
    "NM": {"name": "New Mexico",     "dept": "Office of Superintendent of Insurance",
           "seal": "newMexico-seal.png",     "type": "manual",       "url": None},
    "NY": {"name": "New York",       "dept": "Dept. of Financial Services",
           "seal": "newYork-seal.png",       "type": "manual",       "url": None},
    "NC": {"name": "North Carolina", "dept": "Dept. of Insurance",
           "seal": "northCarolina-seal.svg", "type": "manual",       "url": None},
    "ND": {"name": "North Dakota",   "dept": "Insurance Dept.",
           "seal": "northDakota-seal.png",   "type": "manual",       "url": None},
    "OH": {"name": "Ohio",           "dept": "Dept. of Insurance",
           "seal": "ohio-seal.png",          "type": "manual",       "url": None},
    "OK": {"name": "Oklahoma",       "dept": "Insurance Dept.",
           "seal": "oklahoma-seal.svg",      "type": "license_num",
           "url": "https://sbs.naic.org/solar-external-lookup/lookup/licensee/summary/{LICENSE_NUM}?jurisdiction=OK&entityType=IND&licenseType=PRO"},
    "OR": {"name": "Oregon",         "dept": "Insurance Division",
           "seal": "oregon-seal.svg",        "type": "manual",       "url": None},
    "PA": {"name": "Pennsylvania",   "dept": "Insurance Dept.",
           "seal": "pennsylvania-seal.png",  "type": "manual",       "url": None},
    "RI": {"name": "Rhode Island",   "dept": "Insurance Division",
           "seal": "rhodeIsland-seal.png",   "type": "manual",       "url": None},
    "SC": {"name": "South Carolina", "dept": "Dept. of Insurance",
           "seal": "southCarolina-seal.svg", "type": "npn",
           "url": "https://sbs.naic.org/solar-external-lookup/lookup/licensee/summary/{NPN}?jurisdiction=SC&entityType=IND&licenseType=PRO"},
    "SD": {"name": "South Dakota",   "dept": "Division of Insurance",
           "seal": "southDakota-seal.png",   "type": "manual",       "url": None},
    "TN": {"name": "Tennessee",      "dept": "Dept. of Commerce and Insurance",
           "seal": "tennessee-seal.png",     "type": "manual",       "url": None},
    "TX": {"name": "Texas",          "dept": "Dept. of Insurance",
           "seal": "texas-seal.png",         "type": "manual",       "url": None},
    "UT": {"name": "Utah",           "dept": "Insurance Dept.",
           "seal": "utah-seal.png",          "type": "manual",       "url": None},
    "VT": {"name": "Vermont",        "dept": "Dept. of Financial Regulation",
           "seal": "vermont-seal.svg",       "type": "manual",       "url": None},
    "VA": {"name": "Virginia",       "dept": "Bureau of Insurance",
           "seal": "virginia-seal.png",      "type": "manual",       "url": None},
    "WA": {"name": "Washington",     "dept": "Office of the Insurance Commissioner",
           "seal": "washington-seal.png",    "type": "manual",       "url": None},
    "WV": {"name": "West Virginia",  "dept": "Insurance Commissioner",
           "seal": "westVirginia-seal.png",  "type": "manual",       "url": None},
    "WI": {"name": "Wisconsin",      "dept": "Office of the Commissioner of Insurance",
           "seal": "wisconsin-seal.svg",     "type": "npn",
           "url": "https://sbs.naic.org/solar-external-lookup/lookup/licensee/summary/{NPN}?jurisdiction=WI&entityType=IND&licenseType=INT"},
    "WY": {"name": "Wyoming",        "dept": "Insurance Dept.",
           "seal": "wyoming-seal.png",       "type": "manual",       "url": None},
}


def build_states_for_agent(selected_states, npn, cert_map, errors):
    """
    Takes the list of states the agent is licensed in (from Airtable)
    and builds the data each state card in the HTML template needs.

    selected_states: list like ['FL', 'SC', 'TX']
    npn:             the agent's NPN string e.g. '22168646'
    cert_map:        dict of uploaded certs e.g. {'FL': 'certs/FL.pdf', 'SC': 'certs/SC.pdf'}
    errors:          list to append warnings to (doesn't stop the build)

    Returns a list of dicts, one per state, ready to be passed to the Jinja2 template.
    """
    result = []

    for abbrev in selected_states:
        abbrev = abbrev.strip().upper()
        state_info = STATES.get(abbrev)

        if not state_info:
            errors.append(f"Unknown state code '{abbrev}' in agent's states list — skipped.")
            continue

        # Attempt to build the verify URL
        verify_url = None
        url_type = state_info['type']

        if url_type == 'npn' and npn:
            # We can build this automatically
            verify_url = state_info['url'].replace('{NPN}', str(npn))

        elif url_type == 'license_num':
            # We'd need a state-specific license number — we only have the NPN
            errors.append(
                f"{state_info['name']} ({abbrev}): 'Verify License' button disabled. "
                f"This state's lookup URL requires the state-specific license number, "
                f"not the NPN. Manually find and add the verify URL for this agent."
            )

        elif url_type == 'manual':
            # No parameterized URL exists for this state
            errors.append(
                f"{state_info['name']} ({abbrev}): 'Verify License' button disabled. "
                f"This state's lookup portal does not support a direct link — "
                f"it requires filling out an online form."
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
            'name':          state_info['name'],
            'abbrev':        abbrev,
            'dept':          state_info['dept'],
            'seal_filename': state_info['seal'],
            'npn':           npn,
            'verify_url':    verify_url,   # None if can't be built automatically
            'cert_url':      cert_url,     # None if cert wasn't uploaded
        })

    return result


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