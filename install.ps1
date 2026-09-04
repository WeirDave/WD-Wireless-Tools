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

# Python is the one thing the app cannot run without, and the one thing a new
# machine is least likely to have. It is checked before anything is downloaded,
# because the alternative - what this used to do - is a green "installed"
# message in front of an app that will not start, with nothing saying why.
$PythonMinMajor = 3
$PythonMinMinor = 10
$PythonWingetId = 'Python.Python.3.12'

function Test-PythonStoreStub {
  # Windows ships app-execution aliases for python and python3 that are not
  # interpreters: running one opens the Microsoft Store and exits. On a machine
  # with no real Python these are what "python" resolves to, which is why the
  # old check passed and the app then would not start.
  #
  # They are zero-length reparse points under WindowsApps, so they can be
  # recognised without being run - running one would pop the Store in the
  # middle of an install.
  param([string]$Source)
  if (-not $Source) { return $false }
  if ($Source -notmatch '\\WindowsApps\\') { return $false }
  try { return ((Get-Item -LiteralPath $Source -Force).Length -eq 0) }
  catch { return $true }
}

function Get-PythonInfo {
  # The first interpreter that is real and new enough. A version that is too
  # old is remembered so the message can say what was found rather than just
  # what was wanted.
  $candidates = @(
    @{ Cmd = 'py';      Args = @('-3') },
    @{ Cmd = 'python';  Args = @() },
    @{ Cmd = 'python3'; Args = @() }
  )
  $tooOld = $null
  $sawStub = $false
  foreach ($c in $candidates) {
    $found = Get-Command $c.Cmd -ErrorAction SilentlyContinue
    if (-not $found) { continue }
    if (Test-PythonStoreStub $found.Source) { $sawStub = $true; continue }

    $argList = $c.Args + @('-c', 'import sys;print(sys.version_info[0]*1000+sys.version_info[1])')
    # A candidate that is not an interpreter writes to stderr, and with
    # $ErrorActionPreference = 'Stop' that alone is a terminating error - so a
    # probe that was meant to rule a candidate out would abort the install.
    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try { $out = & $c.Cmd @argList 2>$null } catch { $out = $null }
    finally { $ErrorActionPreference = $prevEap }
    if ($LASTEXITCODE -ne 0 -or -not $out) { continue }
    $code = ("$out" -split "`n")[0].Trim()
    if ($code -notmatch '^\d+$') { continue }

    $major = [int]([int]$code / 1000); $minor = [int]$code % 1000
    $v = "$major.$minor"
    if ($major -gt $PythonMinMajor -or
        ($major -eq $PythonMinMajor -and $minor -ge $PythonMinMinor)) {
      return @{ Ok = $true; Cmd = $c.Cmd; Version = $v; Source = $found.Source }
    }
    if (-not $tooOld -or [version]$v -gt [version]$tooOld) { $tooOld = $v }
  }
  return @{ Ok = $false; TooOld = $tooOld; SawStub = $sawStub }
}

function Install-Python {
  # Same shape as Install-Git: offer it as a step rather than a dead end, and
  # fall back with the reason printed when it cannot succeed.
  if (-not (Test-Winget)) {
    Write-Warn '  winget is not available to install it automatically'
    Write-Warn '  (it ships with newer Windows 10 and 11).'
    return $false
  }

  Write-Step "  Installing Python via winget ($PythonWingetId)..."
  $common = @('install', '--id', $PythonWingetId, '-e',
              '--accept-source-agreements', '--accept-package-agreements',
              '--disable-interactivity')
  & winget @common --scope user 2>&1 | Out-Null
  if ($LASTEXITCODE -ne 0) {
    Write-Host '  Per-user install unavailable; trying the standard installer...'
    & winget @common 2>&1 | Out-Null
  }
  if ($LASTEXITCODE -ne 0) {
    Write-Warn '  The Python install did not complete. This is often a corporate'
    Write-Warn '  policy or a network restriction.'
    return $false
  }

  Update-PathFromRegistry
  $info = Get-PythonInfo
  if (-not $info.Ok) {
    Write-Warn '  Python installed but is not visible yet in this window.'
    Write-Warn '  Close PowerShell, reopen it, and run this again.'
    return $false
  }
  Write-Ok "  Python $($info.Version) installed."
  return $true
}

function Show-PythonMissing {
  param($Info, [bool]$Fatal)
  Write-Host ''
  if ($Info.TooOld) {
    Write-Err "Python $($Info.TooOld) is too old. This needs Python $PythonMinMajor.$PythonMinMinor or newer."
  } elseif ($Info.SawStub) {
    Write-Err "Python is not installed. Windows has a placeholder called 'python'"
    Write-Err "that only opens the Microsoft Store - that is not an interpreter."
  } else {
    Write-Err "Python is not installed. This needs Python $PythonMinMajor.$PythonMinMinor or newer."
  }
  Write-Host ''
  Write-Host '  Get it from https://www.python.org/downloads/'
  Write-Host '  On the first screen, tick "Add python.exe to PATH".'
  Write-Host ''
  Write-Host '  Or from a terminal:'
  Write-Host "    winget install --id $PythonWingetId -e"
  Write-Host ''
  if ($Fatal) {
    Write-Host '  Nothing has been installed. Run this again once Python is in place.'
    Write-Host ''
  }
}

function Confirm-Python {
  # Returns $true when it is safe to carry on.
  param([bool]$Fatal, [bool]$Interactive)

  $info = Get-PythonInfo
  if ($info.Ok) {
    Write-Ok "  Python $($info.Version) found."
    return $true
  }

  Show-PythonMissing -Info $info -Fatal:$false
  if ($Interactive -and (Test-Winget)) {
    $answer = Read-Host 'Install Python now with winget? [Y/n]'
    if ($answer -eq '' -or $answer -match '^[Yy]') {
      if (Install-Python) { return $true }
    }
  }

  if ($Fatal) {
    Write-Host ''
    Write-Err 'Stopping here rather than installing an app that cannot start.'
    Write-Host '  Nothing has been installed. Run this again once Python is in place.'
    Write-Host ''
    if ($Host.Name -eq 'ConsoleHost') { Read-Host 'Press Enter to close' | Out-Null }
    return $false
  }
  Write-Warn '  Updating anyway - the update itself does not need Python, but the'
  Write-Warn '  app will not start until it is installed.'
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

# Before anything is downloaded. A fresh install stops on a missing Python -
# there is no point writing an app that cannot start - while an existing install
# is only warned, because the update itself runs fine without it.
Write-Step 'Checking Python...'
if (-not (Confirm-Python -Fatal:(-not $existing) -Interactive:$interactive)) { exit 1 }

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
  $py = (Get-PythonInfo).Cmd
  if (-not $py) { $py = 'python' }
  $probe = 'import flask, waitress, requests, browser_cookie3, cryptography, keyring, PIL'
  & $py -c $probe *>$null
  if ($LASTEXITCODE -ne 0) {
    Write-Host '  Installing missing packages…'
    & $py -m pip install -q -r (Join-Path $target 'requirements.txt')
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
