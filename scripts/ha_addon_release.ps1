Param(
  [Parameter(Mandatory = $true)]
  [string]$Summary,

  [ValidateSet("patch", "minor", "major")]
  [string]$Bump = "patch",

  # Test command to run before commit/push.
  [string]$TestCommand = "python -m pytest -q",

  # If set, do everything except commit/push (still runs tests).
  [switch]$DryRun,

  # If set, push after successful commit.
  [switch]$Push
)

$ErrorActionPreference = "Stop"

function Fail([string]$Message, [int]$Code = 1) {
  Write-Error $Message
  exit $Code
}

function RequireCommand([string]$Name) {
  if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
    Fail "Missing required command: $Name"
  }
}

function ReadAddonConfigVersion([string]$Path) {
  if (-not (Test-Path $Path)) { Fail "Missing file: $Path" }
  $text = Get-Content -Raw -Encoding UTF8 $Path
  $m = [regex]::Match($text, '^(?<indent>\s*)version:\s*["'']?(?<ver>\d+\.\d+\.\d+)["'']?\s*$', 'Multiline')
  if (-not $m.Success) { Fail "Could not find semver version in $Path" }
  return @{ Version = $m.Groups["ver"].Value; Text = $text }
}

function BumpSemver([string]$Version, [string]$Part) {
  $parts = $Version.Split(".")
  if ($parts.Length -ne 3) { Fail "Invalid semver: $Version" }
  $maj = [int]$parts[0]; $min = [int]$parts[1]; $pat = [int]$parts[2]
  switch ($Part) {
    "major" { $maj += 1; $min = 0; $pat = 0 }
    "minor" { $min += 1; $pat = 0 }
    "patch" { $pat += 1 }
    default { Fail "Unknown bump: $Part" }
  }
  return "$maj.$min.$pat"
}

function WriteAddonConfigVersion([string]$Path, [string]$OriginalText, [string]$NewVersion) {
  $updated = [regex]::Replace(
    $OriginalText,
    '^(?<indent>\s*)version:\s*["'']?\d+\.\d+\.\d+["'']?\s*$',
    "`${indent}version: `"$NewVersion`"",
    'Multiline'
  )
  Set-Content -Path $Path -Value $updated -Encoding UTF8 -NoNewline
  Add-Content -Path $Path -Value "`n" -Encoding UTF8
}

function Run([string]$CommandLine) {
  Write-Host ">> $CommandLine"
  & powershell -NoProfile -ExecutionPolicy Bypass -Command $CommandLine
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

RequireCommand git
RequireCommand python

$repoRoot = (git rev-parse --show-toplevel).Trim()
if (-not $repoRoot) { Fail "Not inside a git repo." }

$addonConfigPath = Join-Path $repoRoot "ha_addons\trading_agent\config.yaml"
$guardPath = Join-Path $repoRoot "scripts\ha_addon_release_guard.py"

$cfg = ReadAddonConfigVersion $addonConfigPath
$oldVersion = $cfg.Version
$oldText = $cfg.Text
$newVersion = BumpSemver $oldVersion $Bump

$subject = "[$newVersion] - $Summary"

Write-Host "Add-on version: $oldVersion -> $newVersion"
Write-Host "Commit subject: $subject"

if ($DryRun) {
  Write-Host "DryRun enabled: not modifying files, committing, or pushing."
  Write-Host "Would run tests: $TestCommand"
  exit 0
}

try {
  # 1) Bump version
  WriteAddonConfigVersion $addonConfigPath $oldText $newVersion

  # 2) Run tests (before commit)
  Run $TestCommand

  # 3) Validate subject/version discipline
  if (Test-Path $guardPath) {
    Run ("python `"{0}`" `"{1}`"" -f $guardPath, $subject.Replace('"', '\"'))
  }

  # 4) Commit
  Run "git add -A"
  Run ("git commit -m `"{0}`"" -f $subject.Replace('"', '\"'))

  # 5) Push (optional)
  if ($Push) {
    Run "git push"
  } else {
    Write-Host "Push skipped (use -Push to push)."
  }
}
catch {
  Write-Error $_
  # Restore only the version bump. Leave other working tree changes intact so you can fix tests and rerun.
  try {
    Set-Content -Path $addonConfigPath -Value $oldText -Encoding UTF8 -NoNewline
  } catch {
    Write-Warning "Failed to restore $addonConfigPath automatically. Please restore it manually."
  }
  Fail "Release command failed. Restored add-on version file; fix issues and rerun."
}

