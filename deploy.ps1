# deploy.ps1 — Rebuild the Lambda package from source and deploy to AWS.
#
# Usage:
#   .\deploy.ps1                  # deploy the Stripe webhook function (default)
#   .\deploy.ps1 -Function admin  # deploy the admin-editor API function
#   .\deploy.ps1 -SyncAdmin       # also sync the admin/ static site to S3
#
# Both Lambdas share ONE zip (same source modules); only the configured Lambda
# handler differs (handler.handler vs admin_api.handler) — set that per-function
# in the AWS console, not here. Run from anywhere — the script self-locates.

param(
    [ValidateSet('function', 'admin')]
    [string]$Function = 'function',
    [switch]$SyncAdmin
)

$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

# Map the friendly arg to the real Lambda name. The hard guard below guarantees we
# can NEVER push application code to verifyanagent-edge-router.
$FunctionName = if ($Function -eq 'admin') { 'verifyanagent-admin' } else { 'verifyanagent-function' }
if ($FunctionName -eq 'verifyanagent-edge-router') { throw "Refusing to deploy to the edge router." }

$ZipPath      = 'lambda_fixed.zip'
$BuildDir     = 'package'

$Sources = @(
    'handler.py',
    'admin_api.py',
    'builder.py',
    'stripe_verifier.py',
    'airtable_client.py',
    's3_manager.py',
    'site_generator.py',
    'state_data.py',
    'cert_ocr.py',
    'notify.py',
    'sitemap.py'
)

# Load deploy config (bucket / distribution ids) for the optional admin-site sync.
$envFile = '.env.deploy'
if (Test-Path $envFile) {
    Get-Content $envFile | ForEach-Object {
        if ($_ -match '^\s*([A-Z_][A-Z0-9_]*)\s*=\s*(.+?)\s*$') {
            Set-Item "env:$($matches[1])" $matches[2]
        }
    }
}

# ── Pre-flight ────────────────────────────────────────────────────────────────
foreach ($tool in 'aws','python','pip') {
    if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) {
        throw "Required tool '$tool' is not on PATH."
    }
}
foreach ($f in $Sources + 'requirements.txt' + 'templates') {
    if (-not (Test-Path $f)) { throw "Missing required source: $f" }
}

# ── Clean ─────────────────────────────────────────────────────────────────────
Write-Host "==> Cleaning previous build artifacts..."
if (Test-Path $BuildDir) { Remove-Item -Recurse -Force $BuildDir }
if (Test-Path $ZipPath)  { Remove-Item -Force $ZipPath }

# ── Install Linux deps ────────────────────────────────────────────────────────
# Lambda runs on Linux x86_64 / py3.12. Without --platform we'd install Windows
# wheels for pydantic-core (an `anthropic` dep) that crash on Lambda.
Write-Host "==> Installing Linux dependencies (manylinux2014_x86_64, py3.12)..."
pip install `
    --platform manylinux2014_x86_64 `
    --target $BuildDir `
    --implementation cp `
    --python-version 3.12 `
    --only-binary=:all: `
    -r requirements.txt | Out-Host
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }

# ── Copy source ───────────────────────────────────────────────────────────────
Write-Host "==> Copying source files..."
foreach ($f in $Sources) { Copy-Item -Path $f -Destination $BuildDir }
Copy-Item -Path templates -Destination "$BuildDir/templates" -Recurse

# ── Build zip with FORWARD-SLASH entries ──────────────────────────────────────
# PS 5.1's Compress-Archive writes backslash zip entries which break on Lambda
# (Linux can't find 'templates\index.html.j2'). Python's zipfile gets it right.
Write-Host "==> Building zip with forward-slash entries..."
$buildZip = @'
import os, sys, zipfile
build_dir, out = sys.argv[1], sys.argv[2]
with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
    for root, dirs, files in os.walk(build_dir):
        dirs[:] = [d for d in dirs if d != '__pycache__']
        for f in files:
            full = os.path.join(root, f)
            rel  = os.path.relpath(full, build_dir).replace(os.sep, '/')
            z.write(full, rel)
'@
$buildZip | python - $BuildDir $ZipPath
if ($LASTEXITCODE -ne 0) { throw "zip build failed" }

$zipSizeMb = [math]::Round((Get-Item $ZipPath).Length / 1MB, 2)
Write-Host "    -> $ZipPath ($zipSizeMb MB)"

# ── Deploy ────────────────────────────────────────────────────────────────────
Write-Host "==> Deploying to Lambda function '$FunctionName'..."
$json = aws lambda update-function-code `
    --function-name $FunctionName `
    --zip-file "fileb://$ZipPath" `
    --output json
if ($LASTEXITCODE -ne 0) { throw "aws lambda update-function-code failed" }

$result = $json | ConvertFrom-Json
Write-Host ""
Write-Host "==> Deploy complete:"
Write-Host "    LastModified : $($result.LastModified)"
Write-Host "    CodeSha256   : $($result.CodeSha256)"
Write-Host "    CodeSize     : $([math]::Round($result.CodeSize / 1MB, 2)) MB"
Write-Host "    Runtime      : $($result.Runtime)"
Write-Host ""
if ($Function -eq 'admin') {
    Write-Host "Deployed the admin API. Ensure the Lambda handler is set to 'admin_api.handler'"
    Write-Host "and these env vars exist: ADMIN_EMAIL, ADMIN_SESSION_SECRET, ADMIN_CORS_ORIGIN,"
    Write-Host "plus the shared AIRTABLE_TOKEN/AIRTABLE_BASE_ID/S3_BUCKET/ANTHROPIC_API_KEY."
} else {
    Write-Host "Next: resend a checkout.session.completed event in Stripe Dashboard,"
    Write-Host "      or run .\trigger.ps1 -Email <agent-email>"
}

# ── Optional: publish the admin static site ───────────────────────────────────
if ($SyncAdmin) {
    # The admin page is served from the agent-sites bucket under the agents/admin/ prefix
    # (the edge router maps admin.verifyanagent.com -> agents/admin). Sync ONLY that prefix,
    # never the bucket root, so customer sites can never be touched or deleted.
    $adminBucket = if ($env:ADMIN_SITE_BUCKET) { $env:ADMIN_SITE_BUCKET } else { 'verifyanagent-agent-sites' }
    $adminTarget = "s3://$adminBucket/agents/admin"
    Write-Host ""
    Write-Host "==> Syncing admin/ to $adminTarget ..."
    aws s3 sync admin $adminTarget | Out-Host
    if ($LASTEXITCODE -ne 0) { throw "aws s3 sync failed" }
    Write-Host "==> Admin site published."
}
