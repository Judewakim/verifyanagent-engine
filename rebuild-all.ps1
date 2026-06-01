# rebuild-all.ps1 — Replay signed webhooks to rebuild every agent's site.
#
# Usage:
#   .\rebuild-all.ps1                # dry run: list agents, no action
#   .\rebuild-all.ps1 -Execute       # actually fire the webhooks (prompts to confirm)
#   .\rebuild-all.ps1 -Execute -Filter "{site_status}='built'"   # custom Airtable filter
#   .\rebuild-all.ps1 -Execute -DelaySeconds 5                   # seconds between calls
#
# Reads from .env.deploy:
#   API_GATEWAY_URL, STRIPE_WEBHOOK_SECRET, AIRTABLE_TOKEN, AIRTABLE_BASE_ID

param(
    [switch]$Execute,
    [int]$DelaySeconds = 2,
    [string]$Filter = "{site_status}='built'"
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

if (-not $env:API_GATEWAY_URL)       { throw "API_GATEWAY_URL not set in .env.deploy" }
if (-not $env:STRIPE_WEBHOOK_SECRET) { throw "STRIPE_WEBHOOK_SECRET not set in .env.deploy" }
if (-not $env:AIRTABLE_TOKEN)        { throw "AIRTABLE_TOKEN not set in .env.deploy" }
if (-not $env:AIRTABLE_BASE_ID)      { throw "AIRTABLE_BASE_ID not set in .env.deploy" }

# ── Fetch agents from Airtable (paginated) ────────────────────────────────────
Write-Host "==> Fetching agents from Airtable (filter: $Filter)..."
$agents  = @()
$offset  = $null
$baseUrl = "https://api.airtable.com/v0/$($env:AIRTABLE_BASE_ID)/Agents"
$headers = @{ Authorization = "Bearer $($env:AIRTABLE_TOKEN)" }

do {
    $url = "$baseUrl" + "?filterByFormula=" + [uri]::EscapeDataString($Filter) + "&pageSize=100"
    if ($offset) { $url += "&offset=$offset" }
    $resp = Invoke-RestMethod -Uri $url -Headers $headers -Method Get -TimeoutSec 30
    foreach ($r in $resp.records) {
        if ($r.fields.email) {
            $agents += [pscustomobject]@{
                Email  = $r.fields.email
                Name   = $r.fields.name
                Status = $r.fields.site_status
            }
        }
    }
    $offset = $resp.offset
} while ($offset)

if ($agents.Count -eq 0) {
    Write-Host "No agents matched the filter. Nothing to do." -ForegroundColor Yellow
    return
}

Write-Host "==> Found $($agents.Count) agent(s):"
$agents | Format-Table -AutoSize

if (-not $Execute) {
    Write-Host ""
    Write-Host "Dry run only. Re-run with -Execute to fire the webhooks." -ForegroundColor Yellow
    return
}

# ── Confirmation ──────────────────────────────────────────────────────────────
Write-Host ""
$confirm = Read-Host "Fire $($agents.Count) webhook(s)? Type 'yes' to proceed"
if ($confirm -ne 'yes') {
    Write-Host "Aborted." -ForegroundColor Yellow
    return
}

# ── Fire webhooks sequentially ────────────────────────────────────────────────
$results = @()
for ($i = 0; $i -lt $agents.Count; $i++) {
    $agent = $agents[$i]
    Write-Host ""
    Write-Host "==> [$($i+1)/$($agents.Count)] $($agent.Name) <$($agent.Email)>" -ForegroundColor Cyan
    $start = Get-Date
    $result = 'OK'
    try {
        & "$PSScriptRoot\trigger.ps1" -Email $agent.Email
    } catch {
        Write-Host "    FAILED: $($_.Exception.Message)" -ForegroundColor Red
        $result = 'FAIL'
    }
    $elapsed = [int]((Get-Date) - $start).TotalSeconds
    $color   = if ($result -eq 'OK') { 'Green' } else { 'Red' }
    Write-Host "    $result in ${elapsed}s" -ForegroundColor $color

    $results += [pscustomobject]@{
        Email   = $agent.Email
        Name    = $agent.Name
        Result  = $result
        Seconds = $elapsed
    }

    if ($DelaySeconds -gt 0 -and $i -lt ($agents.Count - 1)) {
        Start-Sleep -Seconds $DelaySeconds
    }
}

# ── Summary ───────────────────────────────────────────────────────────────────
$ok   = ($results | Where-Object Result -eq 'OK').Count
$fail = ($results | Where-Object Result -eq 'FAIL').Count
Write-Host ""
Write-Host "==> Summary: $ok succeeded, $fail failed"
$results | Format-Table -AutoSize
