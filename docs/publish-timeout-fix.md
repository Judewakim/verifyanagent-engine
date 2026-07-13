# Publish timeout — structural fixes (deferred)

> Hand this to a fresh Claude Code thread. It is self-contained: it explains the bug,
> what has already shipped, and the two remaining fixes with exact file/line pointers.
>
> **Status:** The immediate UI fix (accurate status message instead of a false
> "Publish failed") **has shipped** — see [admin/admin.js](../admin/admin.js) publish
> handler + `pollBuildStatus`. The two fixes below are the *durable* fixes and are
> **not built yet**.

## 1. The problem

Clicking **Publish to live site** in the admin dashboard often showed
**"Publish failed: Failed to fetch"** even though the publish actually succeeded.

- `Publish` calls `POST /admin/agents/{id}/publish` → `_publish`
  ([admin_api.py:496-504](../admin_api.py#L496-L504)), which runs the **entire site
  build synchronously**: a blocking Claude vision OCR call on *every* cert PDF (one at
  a time), asset upload to S3, HTML render, S3 upload, and a full sitemap/directory
  rebuild across all built agents ([builder.py:130-292](../builder.py#L130-L292)).
  This routinely takes 30–60s.
- The Lambda has a 300s budget, but the **API Gateway HTTP API in front of it has a
  hard ~29s integration timeout** that cannot be raised. At ~29s it drops the browser
  connection; the Lambda keeps running and finishes the build.
- The dropped connection makes the browser's `fetch()` reject with a native
  `TypeError: "Failed to fetch"` — a false alarm. The operator's edits were saved (a
  separate `PATCH`) and the build completed server-side, so the page is usually
  already live.

### What already shipped (the band-aid)

[admin/admin.js](../admin/admin.js): the publish handler's `catch` now distinguishes a
gateway timeout (`ex instanceof TypeError`) from a real error. On a timeout it polls
`GET /admin/agents/{id}` for the true `site_status` (`building → built/error`) via the
new `pollBuildStatus` helper and reports the real outcome (`Published → …`,
`Build failed: …`, or a "still running in the background" message) instead of a false
failure. This fixes the *symptom*. The two fixes below remove the *cause*.

## 2. Fix A — Make publish asynchronous (the real fix)

Return immediately and build in the background, so build duration never matters.

- In `handler` ([admin_api.py:729-738](../admin_api.py#L729-L738)), add a branch at the
  very top: if the event carries an async-build marker (e.g. `event.get('async_build')`),
  run `builder.build_site(airtable_client.get_by_id(event['async_build']))` and return.
  (No HTTP response is needed for an `InvocationType='Event'` invoke.)
- Change `_publish` ([admin_api.py:496-504](../admin_api.py#L496-L504)) to self-invoke
  asynchronously instead of building inline:
  ```python
  boto3.client('lambda').invoke(
      FunctionName=os.environ['AWS_LAMBDA_FUNCTION_NAME'],  # built-in Lambda env var
      InvocationType='Event',
      Payload=json.dumps({'async_build': record_id}),
  )
  return _respond(202, {'ok': True, 'async': True})
  ```
- **IAM:** the Lambda execution role needs `lambda:InvokeFunction` permission on itself.
- **Frontend:** the `pollBuildStatus` loop already shipped becomes the *normal* path
  (trigger → poll `site_status`), not just the timeout-recovery path. After this ships,
  the `TypeError` branch is a pure safety net.

**Result:** the publish request returns in <1s; no build ever hits the 29s wall.

## 3. Fix B — Parallelize / trim the per-cert OCR (speed)

The OCR loop ([builder.py:159-200](../builder.py#L159-L200)) makes a blocking
`cert_ocr.extract_cert` Haiku vision call **per state, sequentially** — the dominant
time sink.

- **Parallelize:** run the per-cert calls concurrently (e.g. `ThreadPoolExecutor`). The
  module-level `anthropic.Anthropic` client ([cert_ocr.py:11](../cert_ocr.py#L11)) is
  safe to share across threads. This collapses N states from sum-of-latencies to
  ~one call's latency.
- **Trim (tradeoff — document, don't do silently):** OCR currently runs even when a
  manual `license_numbers_override` exists, *solely* to run the name self-consistency
  check ([builder.py:148-153](../builder.py#L148-L153),
  [builder.py:180-189](../builder.py#L180-L189)). Skipping OCR for overridden states
  would save time but drop the name check for those certs. This is exactly the case
  that triggered the ticket: the MI cert's OCR fails on every publish yet still runs,
  wasting seconds, while the manual override already supplies the number.

With Fix A in place, this is a UX nicety (shorter "building" window), not a correctness
requirement.

## 4. Unrelated flag found during investigation

[env.json](../env.json) with live plaintext secrets (Airtable PAT, Anthropic API key,
session secret, Slack webhook) is present in the working tree, though the docs say it
should be gitignored. Verify it is **not** committed to git history.
