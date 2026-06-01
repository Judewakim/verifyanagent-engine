# trigger.ps1 — Synthesize a Stripe checkout.session.completed webhook and POST
# it to API Gateway, so you can rebuild any agent's site without going through
# Stripe Dashboard.
#
# Usage:  .\trigger.ps1 -Email agent@example.com
#
# Requires API_GATEWAY_URL and STRIPE_WEBHOOK_SECRET. The script loads them from
# .env.deploy (in the repo root, gitignored) or from environment variables.

param(
    [Parameter(Mandatory=$true)]
    [string]$Email
)

$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

# ── Load config ───────────────────────────────────────────────────────────────
$envFile = '.env.deploy'
if (Test-Path $envFile) {
    Get-Content $envFile | ForEach-Object {
        if ($_ -match '^\s*([A-Z_][A-Z0-9_]*)\s*=\s*(.+?)\s*$') {
            Set-Item "env:$($matches[1])" $matches[2]
        }
    }
}

if (-not $env:API_GATEWAY_URL) {
    throw "API_GATEWAY_URL not set. Add it to .env.deploy or as an env var."
}
if (-not $env:STRIPE_WEBHOOK_SECRET) {
    throw "STRIPE_WEBHOOK_SECRET not set. Add it to .env.deploy or as an env var."
}

# ── Build the event payload ───────────────────────────────────────────────────
# The handler only reads customer_details.email and event type — minimal payload.
$timestamp = [int][System.DateTimeOffset]::Now.ToUnixTimeSeconds()
$eventId   = "evt_test_local_$timestamp"
$sessionId = "cs_test_local_$timestamp"

$payload = @{
    id      = $eventId
    object  = 'event'
    type    = 'checkout.session.completed'
    created = $timestamp
    data    = @{
        object = @{
            id     = $sessionId
            object = 'checkout.session'
            customer_details = @{
                email = $Email
            }
        }
    }
} | ConvertTo-Json -Compress -Depth 10

# ── Compute Stripe signature ──────────────────────────────────────────────────
# Format: t={timestamp},v1={hex(HMAC-SHA256(secret, "{timestamp}.{payload}"))}
# Stripe SDK tolerance is 300s — current time satisfies it.
$signedString = "$timestamp.$payload"
$hmac         = New-Object System.Security.Cryptography.HMACSHA256
$hmac.Key     = [Text.Encoding]::UTF8.GetBytes($env:STRIPE_WEBHOOK_SECRET)
$sigBytes     = $hmac.ComputeHash([Text.Encoding]::UTF8.GetBytes($signedString))
$signature    = ($sigBytes | ForEach-Object { $_.ToString('x2') }) -join ''
$hmac.Dispose()

$headers = @{
    'Stripe-Signature' = "t=$timestamp,v1=$signature"
    'Content-Type'     = 'application/json'
}

# ── Send ──────────────────────────────────────────────────────────────────────
Write-Host "==> Synthesizing webhook for $Email"
Write-Host "    Event ID  : $eventId"
Write-Host "    Timestamp : $timestamp"
Write-Host "    Target    : $($env:API_GATEWAY_URL)"
Write-Host ""

try {
    $response = Invoke-RestMethod `
        -Uri $env:API_GATEWAY_URL `
        -Method Post `
        -Headers $headers `
        -Body $payload `
        -TimeoutSec 60
    Write-Host "==> Lambda responded:"
    if ($response -is [string]) { Write-Host $response }
    else { $response | ConvertTo-Json -Depth 10 | Write-Host }
} catch {
    Write-Host "==> Lambda call failed:" -ForegroundColor Red
    Write-Host $_.Exception.Message
    if ($_.Exception.Response) {
        try {
            $stream = $_.Exception.Response.GetResponseStream()
            $reader = New-Object System.IO.StreamReader($stream)
            Write-Host ("Body: " + $reader.ReadToEnd())
        } catch { }
    }
    throw
}
