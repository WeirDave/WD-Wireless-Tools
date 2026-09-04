# install.ps1 — WD Wireless Tools installer and updater (Windows)
#
# Two ways to run it, same script:
#
#   Bootstrap (no install yet, e.g. a work machine):
#     irm https://raw.githubusercontent.com/WeirDave/WD-Wireless-Tools/main/install.ps1 | iex
#
#   Update an existing install:
#     right-click install.ps1 in the app folder -> "Run with PowerShell"
#
# It picks its own mechanism rather than asking:
#   git available  -> clone, then fetch + checkout the newest release tag.
#                     Incremental, and the previous tag stays in the object
#                     store as a rollback.
#   no git         -> download the release ZIP, verify its SHA-256, and
#                     install it, keeping the old folder as a dated backup.
#
# Your settings, cloud session and wall templates live in
# ~/.wd_wireless_tools/ — outside the install folder — so nothing here
# touches your work. See tools/template_store.py for why that split exists.
#
# The app has an Update button that does the same thing (About -> Update now).
# This script is for first installs, locked-down machines, and the case where
# the app won't start.

[CmdletBinding()]
param(
  [string]$Path,
  [ValidateSet('release', 'main')]
  [string]$Channel = 'release',
  # git = tracked checkout, updates in seconds. zip = no dependencies, updates
  # re-download. Omitted on a fresh install means "ask"; on an existing install
  # the method already in use is kept.
  [ValidateSet('git', 'zip', 'ask')]
  [string]$Method = 'ask',
  [switch]$NoLaunch
)

$ErrorActionPreference = 'Stop'

$Repo      = 'WeirDave/WD-Wireless-Tools'
$CloneUrl  = "https://github.com/$Repo.git"
$ApiLatest = "https://api.github.com/repos/$Repo/releases/latest"

function Write-Step($m) { Write-Host $m -ForegroundColor Cyan }
function Write-Ok($m)   { Write-Host $m -ForegroundColor Green }
function Write-Warn($m) { Write-Host $m -ForegroundColor Yellow }
function Write-Err($m)  { Write-Host $m -ForegroundColor Red }

function Test-Git {
  try { & git --version *>$null; return $LASTEXITCODE -eq 0 }
  catch { return $false }
}

function Test-Winget {
  try { & winget --version *>$null; return $LASTEXITCODE -eq 0 }
  catch { return $false }
}

function Update-PathFromRegistry {
  # winget updates PATH for new processes; this one still has the old copy.
  $machine = [Environment]::GetEnvironmentVariable('Path', 'Machine')
  $user    = [Environment]::GetEnvironmentVariable('Path', 'User')
  $env:Path = (@($machine, $user, $env:Path) | Where-Object { $_ }) -join ';'
}

function Install-Git {
  # Windows only. Fast enough (usually under a minute) that a missing Git is
  # offered as a step in the flow rather than a dead end.
  if (Test-Git) { return $true }
  if (-not (Test-Winget)) {
    Write-Warn 'Git is not installed, and winget is not available to install it'
    Write-Warn 'automatically (it ships with newer Windows 10 and 11).'
    Write-Warn 'Install Git from https://git-scm.com, or choose the ZIP method.'
    return $false
  }

  Write-Step 'Installing Git...'
  $common = @('install', '--id', 'Git.Git', '-e',
              '--accept-source-agreements', '--accept-package-agreements',
              '--disable-interactivity')
  # Per-user scope avoids the admin prompt where the package allows it; some
  # Git.Git builds are machine-scope only, so fall back rather than fail.
  & winget @common --scope user 2>&1 | Out-Null
  if ($LASTEXITCODE -ne 0) {
    Write-Host '  Per-user install unavailable; trying the standard installer...'
    & winget @common 2>&1 | Out-Null
  }

  if ($LASTEXITCODE -ne 0) {
    Write-Warn '  The Git install did not complete. This is often a corporate'
    Write-Warn '  policy or a network restriction. Falling back to the ZIP method.'
    return $false
  }

  Update-PathFromRegistry
  if (-not (Test-Git)) {
    Write-Warn '  Git installed but is not visible yet in this window.'
    Write-Warn '  Falling back to the ZIP method for now; reopen PowerShell to use git.'
    return $false
  }
  Write-Ok '  Git installed.'
  return $true
}

function Select-Method {
  # Only asked on a fresh install. An existing install keeps whatever it
  # already uses — the app detects that and shows one Update button.
  param([bool]$GitPresent)

  Write-Host ''
  Write-Host '  How would you like to install?'
  Write-Host ''
  Write-Host '    [1] Git  ' -NoNewline -ForegroundColor Cyan
  Write-Host '- tracked checkout, updates take seconds.' -NoNewline
  if ($GitPresent) { Write-Host ' Git is installed.' }
  else { Write-Host ' Installs Git first (~1 min).' }
  Write-Host '    [2] ZIP  ' -NoNewline -ForegroundColor Cyan
  Write-Host '- no dependencies, each update re-downloads the app.'
  Write-Host ''

  while ($true) {
    $answer = Read-Host 'Choose 1 or 2 [1]'
    if ($answer -eq '' -or $answer -eq '1') { return 'git' }
    if ($answer -eq '2') { return 'zip' }
    Write-Warn '  Enter 1 or 2.'
  }
}

function Invoke-Git {
  param([string[]]$Arguments, [string]$WorkDir, [switch]$AllowFailure)
  $out = & git -C $WorkDir @Arguments 2>&1
  if ($LASTEXITCODE -ne 0 -and -not $AllowFailure) {
    throw "git $($Arguments -join ' ') failed: $out"
  }
  return $out
}

function Get-SuiteVersion($root) {
  $f = Join-Path $root 'web\assets\versions.json'
  if (-not (Test-Path $f)) { return $null }
  try { return (Get-Content -Raw -LiteralPath $f | ConvertFrom-Json).suite }
  catch { return $null }
}

function Compare-SuiteVersion($a, $b) {
  $pa = @(($a -replace '^v','') -split '\.' | ForEach-Object { [int]($_ -as [int]) })
  $pb = @(($b -replace '^v','') -split '\.' | ForEach-Object { [int]($_ -as [int]) })
  for ($i = 0; $i -lt [Math]::Max($pa.Count, $pb.Count); $i++) {
    $av = if ($i -lt $pa.Count) { $pa[$i] } else { 0 }
    $bv = if ($i -lt $pb.Count) { $pb[$i] } else { 0 }
    if ($av -gt $bv) { return 1 }
    if ($av -lt $bv) { return -1 }
  }
  return 0
}

function Get-LatestRelease {
  try {
    $r = Invoke-RestMethod -Uri $ApiLatest -Headers @{ Accept = 'application/vnd.github+json' } -UseBasicParsing
  } catch {
    throw "Could not reach GitHub: $($_.Exception.Message)"
  }
  $tag = [string]$r.tag_name
  if ($tag -notmatch '^v[0-9]+(\.[0-9]+)+$') {
    throw "GitHub returned an unexpected release tag: $tag"
  }
  return $r
}

function Test-InstallTree($root, $expected) {
  foreach ($f in @('server.py', 'requirements.txt', 'web\assets\versions.json')) {
    if (-not (Test-Path (Join-Path $root $f))) {
      throw "Downloaded release is missing expected file: $f"
    }
  }
  foreach ($d in @('tools', 'web', 'templates', 'docs')) {
    if (-not (Test-Path (Join-Path $root $d) -PathType Container)) {
      throw "Downloaded release is missing expected folder: $d"
    }
  }
  $v = Get-SuiteVersion $root
  if (-not $v) { throw "Downloaded release has no readable versions.json" }
  if ($expected -and $v -ne $expected) {
    throw "Downloaded release says v$v but the tag says v$expected"
  }
  return $v
}

# ---- Resolve where we are working -------------------------------------------
# $PSScriptRoot is empty when piped through iex, which is exactly how we tell a
# bootstrap run from an in-folder update.
$scriptDir = $PSScriptRoot
$isInPlace = $false

if ($Path) {
  $target = $Path
} elseif ($scriptDir -and (Test-Path (Join-Path $scriptDir 'server.py'))) {
  $target = $scriptDir
  $isInPlace = $true
} else {
  $target = Join-Path $env:LOCALAPPDATA 'WD Wireless Tools'
}

$existing = Test-Path (Join-Path $target 'server.py')
$currentVersion = if ($existing) { Get-SuiteVersion $target } else { $null }

Write-Host ''
Write-Step 'WD Wireless Tools'
Write-Host "  Folder:  $target"
if ($currentVersion) { Write-Host "  Version: v$currentVersion" }
Write-Host ''

$hasGit = Test-Git
$isGitInstall = Test-Path (Join-Path $target '.git')

# Decide the mechanism. An existing install keeps what it already uses; only a
# fresh install gets a choice, and only when someone is there to answer.
$interactive = ($Host.Name -eq 'ConsoleHost') -and -not $NoLaunch
if ($existing) {
  $method = if ($isGitInstall) { 'git' } else { 'zip' }
} elseif ($Method -ne 'ask') {
  $method = $Method
} elseif ($interactive) {
  $method = Select-Method -GitPresent $hasGit
} else {
  $method = if ($hasGit) { 'git' } else { 'zip' }
}

# Git chosen but missing: offer to install it rather than dead-ending. If that
# cannot succeed (no winget, no network, blocked by policy), fall through to
# ZIP with the reason already printed.
if ($method -eq 'git' -and -not $hasGit) {
  if (Install-Git) { $hasGit = $true } else { $method = 'zip' }
}
if ($method -eq 'git' -and -not $hasGit) { $method = 'zip' }

try {
  # ---- git path ---------------------------------------------------------------
  if ($method -eq 'git' -and ($isGitInstall -or -not $existing)) {

    if (-not $existing -and -not $isGitInstall) {
      Write-Step "Cloning $Repo…"
      New-Item -ItemType Directory -Path $target -Force | Out-Null
      & git clone --quiet $CloneUrl $target
      if ($LASTEXITCODE -ne 0) { throw "Clone failed. Check your network or proxy settings." }
    } else {
      Write-Step 'Fetching updates…'
      Invoke-Git -Arguments @('fetch', '--tags', '--prune', 'origin') -WorkDir $target | Out-Null
    }

    if ($Channel -eq 'main') {
      $ref = 'origin/main'
      $label = 'main'
    } else {
      $tags = Invoke-Git -Arguments @('tag', '--list', 'v*') -WorkDir $target |
              Where-Object { $_ -match '^v[0-9]+(\.[0-9]+)+$' }
      if (-not $tags) { throw 'No release tags found on the remote.' }
      $ref = ($tags | Sort-Object { [version]($_ -replace '^v','') } | Select-Object -Last 1)
      $label = $ref
    }

    if ($currentVersion -and $Channel -eq 'release' -and
        (Compare-SuiteVersion ($ref -replace '^v','') $currentVersion) -le 0) {
      Write-Ok "Already up to date (v$currentVersion)."
    } else {
      # Preserve an in-place edit to a shipped template before it blocks the
      # checkout. The app reads user templates from ~/.wd_wireless_tools.
      $dirty = Invoke-Git -Arguments @('status', '--porcelain', '--', 'templates') -WorkDir $target -AllowFailure
      foreach ($line in @($dirty)) {
        if ("$line" -match '^\s*M\s+(.*_walltemplate\.json)$') {
          $rel = $Matches[1].Trim('"')
          $leaf = Split-Path -Leaf $rel
          $userDir = Join-Path $HOME '.wd_wireless_tools\templates'
          New-Item -ItemType Directory -Path $userDir -Force | Out-Null
          $dest = Join-Path $userDir $leaf
          if (-not (Test-Path $dest)) {
            Copy-Item -LiteralPath (Join-Path $target $rel) -Destination $dest
            Write-Warn "  Kept your customized $leaf as a personal copy."
          }
          Invoke-Git -Arguments @('checkout', '--', $rel) -WorkDir $target -AllowFailure | Out-Null
        }
      }

      Write-Step "Checking out $label…"
      Invoke-Git -Arguments @('-c', 'advice.detachedHead=false', 'checkout', '--force', $ref) -WorkDir $target | Out-Null
      $newVersion = Get-SuiteVersion $target
      if ($currentVersion) { Write-Ok "Updated v$currentVersion -> v$newVersion" }
      else { Write-Ok "Installed v$newVersion" }
    }
  }
  # ---- ZIP path ---------------------------------------------------------------
  else {
    if (-not $hasGit -and -not $existing) {
      Write-Warn 'Using the ZIP method. Each update re-downloads the app.'
      Write-Warn 'You can switch to git updates later from Menu -> About.'
    }

    $release = Get-LatestRelease
    $tag = [string]$release.tag_name
    $version = $tag -replace '^v',''

    if ($currentVersion -and (Compare-SuiteVersion $version $currentVersion) -le 0) {
      Write-Ok "Already up to date (v$currentVersion)."
    } else {
      $assetName = "WD-Wireless-Tools-$tag.zip"
      $asset = $release.assets | Where-Object { $_.name -eq $assetName } | Select-Object -First 1
      if (-not $asset) { throw "Release $tag has no $assetName asset." }

      $staging = Join-Path $env:TEMP "WDWirelessToolsUpdate-$([guid]::NewGuid().ToString('N'))"
      New-Item -ItemType Directory -Path $staging -Force | Out-Null
      try {
        $zip = Join-Path $staging 'release.zip'
        Write-Step "Downloading $tag…"
        Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $zip -UseBasicParsing

        $sum = $release.assets | Where-Object { $_.name -eq "$assetName.sha256" } | Select-Object -First 1
        if ($sum) {
          Write-Step 'Verifying SHA-256…'
          $sumFile = Join-Path $staging 'release.sha256'
          Invoke-WebRequest -Uri $sum.browser_download_url -OutFile $sumFile -UseBasicParsing
          $text = (Get-Content -Raw -LiteralPath $sumFile).Trim()
          if ($text -notmatch '^(?<hash>[A-Fa-f0-9]{64})\b') { throw 'Checksum file is malformed.' }
          $expected = $Matches['hash'].ToLowerInvariant()
          $actual = (Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash.ToLowerInvariant()
          if ($actual -ne $expected) {
            throw "SHA-256 mismatch — expected $expected, got $actual. The download was not used."
          }
          Write-Ok "  Verified $actual"
        } else {
          Write-Warn '  No checksum published for this release; skipping verification.'
        }

        Write-Step 'Extracting…'
        $extract = Join-Path $staging 'extracted'
        Expand-Archive -LiteralPath $zip -DestinationPath $extract -Force
        $tree = $extract
        $kids = @(Get-ChildItem -LiteralPath $extract)
        if ($kids.Count -eq 1 -and $kids[0].PSIsContainer) { $tree = $kids[0].FullName }

        Write-Step 'Verifying contents…'
        $newVersion = Test-InstallTree $tree $version
        Write-Ok "  v$newVersion, all expected files present."

        if ($existing) {
          $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
          $backup = Join-Path (Split-Path -Parent $target) `
                              ("{0}.previous-v{1}-{2}" -f (Split-Path -Leaf $target), $currentVersion, $stamp)
          Write-Step 'Backing up the current install…'
          Copy-Item -LiteralPath $target -Destination $backup -Recurse -Force
          Write-Host "  $backup"
        }

        Write-Step 'Installing…'
        New-Item -ItemType Directory -Path $target -Force | Out-Null
        Copy-Item -Path (Join-Path $tree '*') -Destination $target -Recurse -Force

        if ($currentVersion) { Write-Ok "Updated v$currentVersion -> v$newVersion" }
        else { Write-Ok "Installed v$newVersion" }
      } finally {
        Remove-Item -LiteralPath $staging -Recurse -Force -ErrorAction SilentlyContinue
      }
    }
  }

  # ---- Dependencies ------------------------------------------------------------
  Write-Step 'Checking Python dependencies…'
  $probe = 'import flask, waitress, requests, browser_cookie3, cryptography, keyring, PIL'
  & python -c $probe *>$null
  if ($LASTEXITCODE -ne 0) {
    Write-Host '  Installing missing packages…'
    & python -m pip install -q -r (Join-Path $target 'requirements.txt')
    if ($LASTEXITCODE -ne 0) {
      Write-Warn '  Some packages failed to install. Run the launcher to see details.'
    }
  } else {
    Write-Ok '  All dependencies present.'
  }

  Write-Host ''
  Write-Ok "Ready: $target"
  Write-Host '  Start it with "Start WD Wireless Tools.bat"'
  Write-Host ''

  if (-not $NoLaunch -and -not $isInPlace) {
    $bat = Join-Path $target 'Start WD Wireless Tools.bat'
    if (Test-Path $bat) {
      $answer = Read-Host 'Launch it now? [Y/n]'
      if ($answer -eq '' -or $answer -match '^[Yy]') {
        Start-Process -FilePath $bat -WorkingDirectory $target
      }
    }
  }
} catch {
  Write-Host ''
  Write-Err "Failed: $($_.Exception.Message)"
  Write-Err 'Nothing was left half-installed.'
  Write-Host ''
  Write-Host "Releases: https://github.com/$Repo/releases"
  if ($Host.Name -eq 'ConsoleHost') { Read-Host 'Press Enter to close' | Out-Null }
  exit 1
}

if ($isInPlace -and $Host.Name -eq 'ConsoleHost') {
  Read-Host 'Press Enter to close' | Out-Null
}
