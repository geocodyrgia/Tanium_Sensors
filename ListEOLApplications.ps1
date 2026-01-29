<# =====================================================================
 Sensor-ListEOLApplications.ps1  (Local File Version)
 -----------------------------------------------------------------------
 PURPOSE
  - Read the local JSON produced by Build-TaniumEOLInventory.ps1 and
    emit rows for Reporting:
      App|Version|EolDate|IsEol

 PARAMETERS
  - JsonPath: Full path to local eol_inventory.json (no URLs)
  - OnlyEol : If set, print only IsEol = "Yes"
  - MaxRows : Safety cap for extremely large files
  - ControllerName: If set and current host doesn't match, prints "Skip"
    (prevents duplicate rows if the sensor is targeted broadly).

 ROBUSTNESS
  - Validates path, enforces size/row caps, catches and reports errors
    without throwing unhandled exceptions.

 USAGE EXAMPLE (Tanium)
  - Create a PowerShell sensor with this body.
  - Parameter "JsonPath" default: C:\ProgramData\Tanium\EOL\eol_inventory.json
  - Ask from the controller only:
    Get Sensor-ListEOLApplications("C:\ProgramData\Tanium\EOL\eol_inventory.json", OnlyEol, ControllerName:"TANIUM-CONTROLLER1")
 ===================================================================== #>

[CmdletBinding()]
param(
  [Parameter(Mandatory=$true)]
  [ValidateNotNullOrEmpty()]
  [string]$JsonPath,

  [switch]$OnlyEol,

  [ValidateRange(1,1000000)]
  [int]$MaxRows = 1000000,

  [string]$ControllerName
)

try {
  # 1) Optional single-host gating to avoid duplicate result rows
  if ($ControllerName) {
    $me = $env:COMPUTERNAME
    if ($me -ne $ControllerName) {
      Write-Output "Skip"
      return
    }
  }

  # 2) Validate local path and reasonable size (e.g., 200 MB cap)
  if (-not (Test-Path -Path $JsonPath -PathType Leaf)) {
    Write-Output "Error: JSON path not found"
    return
  }
  $file = Get-Item -LiteralPath $JsonPath -ErrorAction Stop
  if ($file.Length -gt 200MB) {
    Write-Output "Error: JSON file too large"
    return
  }

  # 3) Read and parse JSON safely
  $raw = Get-Content -LiteralPath $JsonPath -Raw -Encoding UTF8
  if ([string]::IsNullOrWhiteSpace($raw)) {
    Write-Output "Error: JSON file is empty"
    return
  }
  $data = $null
  try { $data = $raw | ConvertFrom-Json -ErrorAction Stop }
  catch { Write-Output ("Error: invalid JSON - {0}" -f $_.Exception.Message); return }

  if ($null -eq $data.apps) {
    Write-Output "Error: invalid JSON (missing 'apps')"
    return
  }

  # 4) Filter and cap
  $rows = @($data.apps)
  if ($OnlyEol) {
    $rows = $rows | Where-Object { $_.is_eol -eq 'Yes' }
  }
  if ($rows.Count -gt $MaxRows) {
    $rows = $rows[0..($MaxRows-1)]
  }

  # 5) Emit lines for Reporting: App|Version|EolDate|IsEol
  if (-not $rows -or $rows.Count -eq 0) {
    Write-Output "None"
    return
  }
  foreach ($r in $rows) {
    $app = [string]$r.app
    if ([string]::IsNullOrWhiteSpace($app)) { continue }
    $ver = [string]$r.version
    $eol = [string]$r.eol_date
    $iso = [string]$r.is_eol
    "{0}|{1}|{2}|{3}" -f $app, $ver, $eol, $iso
  }
}
catch {
  Write-Output ("Error: {0}" -f $_.Exception.Message)
}
