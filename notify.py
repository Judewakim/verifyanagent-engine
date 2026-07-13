# notify.py — operator alerts when a build needs a human look.
#
# Fired from builder.build_site (via its _result() exit point) whenever a completed
# build accumulated warnings — an OCR miss, a name mismatch, or an asset/upload
# failure. The important case is the Stripe-webhook build: a new paid signup
# auto-builds while nobody is watching the dashboard, and these cases need review.
# This pushes an alert to Slack, whose mobile app delivers it as a phone
# notification, with a deep link straight to the agent in the admin editor.
#
# Config (env vars, both optional):
#   SLACK_WEBHOOK_URL — a Slack Incoming Webhook URL. If unset, alerting is skipped
#                       (safe no-op, like TURNSTILE_SECRET) so local/dev never breaks.
#   ADMIN_URL         — base URL of the admin dashboard, for the deep link.
#                       Defaults to https://admin.verifyanagent.com
import os

import requests

_ADMIN_URL = os.environ.get('ADMIN_URL', 'https://admin.verifyanagent.com').rstrip('/')


def notify_review(agent_name, record_id, site_url, warnings, ok=True):
    """POST a 'needs review' alert to Slack. Best-effort — never raises.

    Called only when there is something to review (a non-empty `warnings` list).
    """
    if not warnings:
        return

    webhook = os.environ.get('SLACK_WEBHOOK_URL')
    if not webhook:
        print('SLACK_WEBHOOK_URL not set — skipping review alert')
        return

    deep_link = f'{_ADMIN_URL}/#{record_id}'
    # Use Slack emoji shortcodes (rendered reliably by Slack) and keep the rest of
    # the message plain ASCII so nothing can mojibake in transit.
    header = (':red_circle: Build FAILED - needs review' if not ok
              else ':warning: Page built with warnings - needs review')
    issues = '\n'.join(f'- {w}' for w in warnings)
    text = (
        f'*{header}*\n'
        f'*Agent:* {agent_name or "(unknown)"}\n'
        + (f'*Page:* {site_url}\n' if site_url else '')
        + f'*Open in admin:* {deep_link}\n'
        f'*Issues:*\n{issues}'
    )

    try:
        requests.post(webhook, json={'text': text}, timeout=10)
    except Exception as e:
        print(f'Review alert failed to send (non-fatal): {e}')
