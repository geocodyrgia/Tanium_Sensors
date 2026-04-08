<# =====================================================================
 Sensor-ListEOLApplications.ps1  (Hard-coded JSON path, no controller gating)

 PURPOSE
  - Read a local JSON file (written by your builder job) and emit rows
    for Reporting/Dashboards in the format:
        App|Version|EolDate|IsEol

 PARAMETERS
  - OnlyEol : If set, emit only rows where IsEol = "Yes".
  - MaxRows : Safety cap for very large outputs (default 1,000,000).

 OUTPUT
  - "App|Version|EolDate|IsEol" per application row found in JSON.
  - "None" if no rows exist after filtering.
  - "Error: <message>" on file/parse issues (never throws).

 NOTES
  - The set of endpoints to run on is controlled entirely by your Tanium
    targeting; there is no host gating in the script.
 ===================================================================== #>

[CmdletBinding()]
param(
  [switch]$OnlyEol,

  [ValidateRange(1,1000000)]
  [int]$MaxRows = 1000000
)

# >>> HARD-CODED STANDARD PATH (aligned with builder) <<<
$JsonPath = 'C:\ProgramData\Tanium\EOL\eol_inventory.json'

# Safety limits to protect the console
$MaxFileBytes = 200MB

try {
  # 1) Validate presence & size
  if (-not (Test-Path -Path $JsonPath -PathType Leaf)) { 'Error: JSON path not found'; return }
  $file = Get-Item -LiteralPath $JsonPath -ErrorAction Stop
  if ($file.Length -gt $MaxFileBytes) { 'Error: JSON file too large'; return }

  # 2) Read & parse JSON
  $raw = Get-Content -LiteralPath $JsonPath -Raw -Encoding UTF8
  if ([string]::IsNullOrWhiteSpace($raw)) { 'Error: JSON file is empty'; return }

  $data = $null
  try { $data = $raw | ConvertFrom-Json -ErrorAction Stop }
  catch { "Error: invalid JSON - $($_.Exception.Message)"; return }

  if ($null -eq $data.apps) { "Error: invalid JSON (missing 'apps')"; return }

  # 3) Optionally filter to only EOL items; cap the output size
  $rows = @($data.apps)
  if ($OnlyEol) { $rows = $rows | Where-Object { $_.is_eol -eq 'Yes' } }

  if (-not $rows -or $rows.Count -eq 0) { 'None'; return }
  if ($rows.Count -gt $MaxRows) { $rows = $rows[0..($MaxRows - 1)] }

  # 4) Emit: App|Version|EolDate|IsEol
  foreach ($r in $rows) {
    $app = [string]$r.app; if ([string]::IsNullOrWhiteSpace($app)) { continue }
    $ver = [string]$r.version
    $eol = [string]$r.eol_date
    $iso = [string]$r.is_eol  # "Yes"/"No"
    '{0}|{1}|{2}|{3}' -f $app, $ver, $eol, $iso
  }
}
catch {
  "Error: $($_.Exception.Message)"
}
