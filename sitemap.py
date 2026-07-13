# sitemap.py — regenerate sitemap.xml AND the public agent directory (directory.html)
# from the current set of BUILT agents, then upload both to the site's bucket root.
#
# Why both live here: they share one Airtable read and one definition of "which
# agents are live," so keeping them together guarantees the sitemap and the
# human-facing directory never drift out of sync.
#
# Called at the end of a successful builder.build_site() so both refresh whenever
# an agent is published. Also runnable standalone for a one-off rebuild:
#     python -c "import sitemap; sitemap.build_and_upload()"
#
# Cross-subdomain note: the sitemap lists https://{slug}.verifyanagent.com URLs.
# Google only accepts a sitemap that spans subdomains when it is submitted under a
# Search Console *Domain* property for verifyanagent.com (which covers every
# subdomain). A URL-prefix property for the apex alone will reject those URLs.
import os
import html
from xml.sax.saxutils import escape

import airtable_client
import s3_manager
import state_data

APEX = 'https://verifyanagent.com'

# Static apex pages worth listing in the sitemap. Extensionless, matching how the
# edge router serves the hand-written apex pages (e.g. /get-started -> get-started.html).
APEX_PATHS = [
    '/',
    '/get-started',
    '/directory',
    '/how-to-verify-a-life-insurance-agent',
    '/check-insurance-agent-license',
]


# ── Data ────────────────────────────────────────────────────────────────────────
def _built_agents():
    """Every published agent as {name, slug, url, states}. Mirrors admin_api's
    _list_agents_public: keep only site_status == 'built' and resolve the slug the
    same way the build does, so the directory URL always matches the live page."""
    records = airtable_client.list_all(
        fields=['name', 'subdomain', 'site_status', 'states']
    )
    agents = []
    for r in records:
        f = r['fields']
        if f.get('site_status') != 'built':
            continue
        slug = s3_manager.resolve_slug(f)
        if not slug:
            continue
        agents.append({
            'name':   f.get('name', '') or slug,
            'slug':   slug,
            'url':    f'https://{slug}.verifyanagent.com',
            'states': f.get('states', []) or [],
        })
    agents.sort(key=lambda a: a['name'].lower())
    return agents


def _states_label(abbrevs):
    """Human label for a list of state abbreviations, e.g. ['FL','TX','GA','NY','CA']
    -> 'Florida, Texas, Georgia and 2 more'. Unknown codes are skipped."""
    names = [state_data.STATES[a]['name'] for a in abbrevs if a in state_data.STATES]
    if not names:
        return ''
    if len(names) <= 4:
        return ', '.join(names)
    return f"{', '.join(names[:4])} and {len(names) - 4} more"


# ── Renderers ───────────────────────────────────────────────────────────────────
def render_sitemap(agents):
    urls = [f'{APEX}{p}' for p in APEX_PATHS] + [a['url'] for a in agents]
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    for u in urls:
        lines.append(f'  <url><loc>{escape(u)}</loc></url>')
    lines.append('</urlset>')
    return '\n'.join(lines) + '\n'


def render_directory(agents):
    """A static, crawlable list of every verified agent. Real <a> anchors (not JS)
    so search engines can follow them to each agent's subdomain — this is the link
    graph that makes the individual agent pages discoverable. A small progressive-
    enhancement script filters the list from a ?q= parameter for the searchbox."""
    if agents:
        items = '\n'.join(
            f'      <li class="agent" data-name="{html.escape(a["name"]).lower()}">'
            f'<a href="{html.escape(a["url"])}">{html.escape(a["name"])}</a>'
            f'<span class="states">{html.escape(_states_label(a["states"]))}</span></li>'
            for a in agents
        )
        count_note = f'{len(agents)} verified agent' + ('s' if len(agents) != 1 else '')
    else:
        items = '      <li class="empty">No verified agents are listed yet.</li>'
        count_note = 'Directory'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Verified Insurance Agents Directory — VerifyAnAgent</title>
  <meta name="description" content="Browse every insurance professional with a live VerifyAnAgent license verification page. Each links to official state Department of Insurance records." />
  <meta name="robots" content="index, follow" />
  <link rel="canonical" href="{APEX}/directory" />
  <meta property="og:type" content="website" />
  <meta property="og:site_name" content="VerifyAnAgent" />
  <meta property="og:title" content="Verified Insurance Agents Directory — VerifyAnAgent" />
  <meta property="og:description" content="Browse every insurance professional with a live VerifyAnAgent license verification page." />
  <meta property="og:url" content="{APEX}/directory" />
  <meta property="og:image" content="{APEX}/websiteCreationLogo-nobackground.png" />
  <link rel="icon" type="image/png" href="{APEX}/websiteCreationLogo-nobackground.png" />
  <style>
    :root {{ --navy:#112e51; --primary:#205493; --ink:#1b1b1b; --ink-mid:#4c5560; --line:#dcdee0; --bg-alt:#f6f7f9; }}
    * {{ box-sizing:border-box; margin:0; padding:0; }}
    body {{ font-family:'Public Sans',system-ui,-apple-system,sans-serif; color:var(--ink); line-height:1.6; background:#fff; }}
    .wrap {{ max-width:800px; margin:0 auto; padding:3rem 1.5rem 5rem; }}
    a {{ color:var(--primary); }}
    header a.home {{ font-size:.85rem; text-decoration:none; color:var(--ink-mid); }}
    h1 {{ font-family:Georgia,'Times New Roman',serif; color:var(--navy); font-size:2rem; margin:1rem 0 .35rem; }}
    .lede {{ color:var(--ink-mid); margin-bottom:1.75rem; }}
    .search {{ width:100%; padding:.75rem 1rem; font-size:1rem; border:1px solid var(--line); border-radius:6px; margin-bottom:1.5rem; }}
    ul {{ list-style:none; border-top:1px solid var(--line); }}
    li.agent {{ display:flex; justify-content:space-between; align-items:baseline; gap:1rem; padding:.85rem .25rem; border-bottom:1px solid var(--line); }}
    li.agent a {{ font-weight:600; text-decoration:none; }}
    li.agent a:hover {{ text-decoration:underline; }}
    .states {{ color:var(--ink-mid); font-size:.85rem; text-align:right; }}
    li.empty {{ padding:1.5rem .25rem; color:var(--ink-mid); }}
    .count {{ color:var(--ink-mid); font-size:.8rem; margin-top:1.25rem; }}
    footer {{ margin-top:2.5rem; color:var(--ink-mid); font-size:.8rem; }}
  </style>
</head>
<body>
  <div class="wrap">
    <header><a class="home" href="{APEX}/">&larr; VerifyAnAgent</a></header>
    <h1>Verified insurance agents</h1>
    <p class="lede">Every insurance professional below has a live VerifyAnAgent page. Each links directly to official state Department of Insurance records and the National Producer Number registry.</p>
    <input class="search" id="q" type="search" placeholder="Filter by name…" aria-label="Filter agents by name" autocomplete="off" />
    <ul id="list">
{items}
    </ul>
    <p class="count">{count_note}</p>
    <footer>VerifyAnAgent is an independent service and is not a government agency.</footer>
  </div>
  <script>
    (function () {{
      var input = document.getElementById('q');
      var items = Array.prototype.slice.call(document.querySelectorAll('li.agent'));
      function apply(term) {{
        term = (term || '').trim().toLowerCase();
        items.forEach(function (li) {{
          li.style.display = !term || li.getAttribute('data-name').indexOf(term) !== -1 ? '' : 'none';
        }});
      }}
      var q = new URLSearchParams(location.search).get('q');
      if (q) {{ input.value = q; apply(q); }}
      input.addEventListener('input', function () {{ apply(input.value); }});
    }})();
  </script>
</body>
</html>
"""


# ── Upload ──────────────────────────────────────────────────────────────────────
def _upload_root(key, body, content_type):
    """Write an object to the bucket ROOT (the apex site's document root), not under
    agents/. The S3 origin is uncached, so the object is live immediately — no
    CloudFront invalidation (project rule: never invalidate)."""
    s3_manager.s3.put_object(
        Bucket=os.environ['S3_BUCKET'],
        Key=key,
        Body=body.encode('utf-8'),
        ContentType=content_type,
    )
    print(f'  Uploaded (root): {key}')


def build_and_upload():
    """Regenerate sitemap.xml + directory.html from the live agent set and upload
    both to the bucket root. Returns the number of agents listed."""
    agents = _built_agents()
    _upload_root('sitemap.xml', render_sitemap(agents), 'application/xml; charset=utf-8')
    # Extensionless key so the page is served at /directory (the apex site's clean-URL
    # convention — the object KEY is the URL path; see apex_site/README.md).
    _upload_root('directory', render_directory(agents), 'text/html; charset=utf-8')
    print(f'Sitemap + directory rebuilt with {len(agents)} agent(s).')
    return len(agents)


if __name__ == '__main__':
    build_and_upload()
