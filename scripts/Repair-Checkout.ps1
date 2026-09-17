# Repair-Checkout.ps1 - put a git install back on the published history.
#
# WHY THIS EXISTS
#
# On 2026-09-17 this repository's history was rewritten to take real workplace
# identifiers out of old commits and old versions of files. A rewrite gives
# every commit a new id, so a checkout made before it is not merely behind the
# remote - it is on a history that no longer exists upstream. `git pull` does
# not report that as being behind. It says:
#
#     fatal: refusing to merge unrelated histories
#
# and the usual advice for that message - allow the merge, or rebase - would
# drag the old commits straight back in, which is the one thing the rewrite
# was for.
#
# The fix is to discard the local history and take the remote's. That is safe
# here and would not be elsewhere: this is a checkout of a published project
# that nobody commits to locally, so everything in it came from the remote in
# the first place.
#
# WHAT IT DOES
#
#   1. checks this really is the WD Wireless Tools checkout, and stops if not
#   2. copies anything uncommitted to a dated folder OUTSIDE the repo and says
#      where - nothing is discarded silently
#   3. fetches, forces the tags across (all 217 of them moved too), and resets
#      to origin/main
#   4. expires the reflog and garbage-collects, so the old commits - the ones
#      carrying the identifiers - stop existing on this machine as well
#   5. prints the version it ended on, so you can see that it worked
#
# WHAT IT DOES NOT TOUCH
#
# Settings, logs, wall templates and share recipients all live in
# %USERPROFILE%\.wd_wireless_tools, outside the install tree on purpose. This
# never goes near them.
#
#   powershell -ExecutionPolicy Bypass -File .\scripts\Repair-Checkout.ps1
#
# Run it once. Running it again is harmless - it will say there is nothing to
# do.

$ErrorActionPreference = 'Stop'

function Say($text)  { Write-Host $text }
function Step($text) { Write-Host ""; Write-Host "== $text" }

# git writes ordinary progress to stderr - the tag list, "From <url>", all of
# it. With $ErrorActionPreference = 'Stop' in force, PowerShell turns that into
# a terminating NativeCommandError, and the script dies having done nothing on
# a fetch that actually succeeded. That happened on the first run of this, and
# is only visible by running it.
#
# So every git call goes through here: stderr is folded into stdout with the
# preference relaxed for the duration, and the verdict is taken from
# $LASTEXITCODE, which is the only thing that really says whether git failed.
function Git-Run {
    $old = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $output = & git @args 2>&1 | ForEach-Object { "$_" }
        $code = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $old
    }
    return [pscustomobject]@{
        Ok     = ($code -eq 0)
        Code   = $code
        Output = $output
        Text   = ($output -join "`n").Trim()
    }
}

# --- where are we -----------------------------------------------------------

$root = Split-Path -Parent $PSScriptRoot
if (-not $root) { $root = (Get-Location).Path }
Set-Location $root

Say "WD Wireless Tools - checkout repair"
Say "Install folder: $root"

if (-not (Test-Path (Join-Path $root '.git'))) {
    Say ""
    Say "This is not a git install - there is no .git folder here."
    Say "ZIP installs are unaffected by the history rewrite. Use the Update"
    Say "button in About, or re-run install.ps1, and you are done."
    exit 0
}

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Say ""
    Say "git is not on PATH, so this cannot run."
    Say "Install it with:  winget install Git.Git --scope user"
    exit 1
}

$remote = (Git-Run remote get-url origin).Text
if (-not $remote -or $remote -notmatch 'WD-Wireless-Tools') {
    Say ""
    Say "The 'origin' remote here does not look like WD Wireless Tools:"
    Say "  $remote"
    Say "Stopping rather than resetting a repository this was not written for."
    exit 1
}

# --- is there anything to do ------------------------------------------------

Step "Checking against GitHub"

$fetch = Git-Run fetch --prune --tags --force origin
if (-not $fetch.Ok) {
    Say ""
    Say "Could not reach GitHub (git exit code $($fetch.Code)):"
    Say $fetch.Text
    Say ""
    Say "Nothing has been changed. Try again from a network that can reach"
    Say "github.com."
    exit 1
}

$local  = (Git-Run rev-parse HEAD).Text
$target = (Git-Run rev-parse origin/main).Text
$dirty  = (Git-Run status --porcelain).Output | Where-Object { $_ }

if ($local -eq $target -and -not $dirty) {
    Say "Already on the published history and nothing is modified."
    Say "Nothing to do."
    exit 0
}

if ($local -eq $target) {
    Say "Already on the published history, but some files are modified."
} else {
    Say "This checkout is on the old history. Repairing."
}

# --- keep anything uncommitted ----------------------------------------------

Step "Saving anything you have changed"

if ($dirty) {
    $stamp  = Get-Date -Format 'yyyy-MM-dd-HHmmss'
    $backup = Join-Path (Split-Path -Parent $root) ("WD-checkout-backup-" + $stamp)
    New-Item -ItemType Directory -Path $backup -Force | Out-Null
    $saved = 0
    foreach ($line in $dirty) {
        $rel = $line.Substring(3).Trim('"')
        if ($rel -match ' -> ') { $rel = ($rel -split ' -> ')[-1] }
        $src = Join-Path $root $rel
        if (Test-Path $src -PathType Leaf) {
            $dest = Join-Path $backup $rel
            New-Item -ItemType Directory -Path (Split-Path -Parent $dest) -Force | Out-Null
            Copy-Item $src $dest -Force
            $saved++
        }
    }
    Say "Copied $saved changed file(s) to:"
    Say "  $backup"
    Say "Nothing was deleted. Remove that folder yourself once you are happy."
} else {
    Say "Nothing is modified - nothing to save."
}

# --- take the remote's history ----------------------------------------------

Step "Moving onto the published history"

$branch = (Git-Run rev-parse --abbrev-ref HEAD).Text
if ($branch -ne 'main') {
    Say "Currently on '$branch'; switching to main."
    $co = Git-Run checkout -B main --track origin/main
    if (-not $co.Ok) {
        Say "Could not switch to main:"
        Say $co.Text
        exit 1
    }
}

$reset = Git-Run reset --hard origin/main
if (-not $reset.Ok) {
    Say "The reset failed:"
    Say $reset.Text
    exit 1
}

$now = (Git-Run rev-parse HEAD).Text
if ($now -ne $target) {
    Say ""
    Say "The reset did not land where it should have."
    Say "  wanted: $target"
    Say "  got:    $now"
    Say "Stopping here rather than carrying on."
    exit 1
}

# --- and let the old commits go ---------------------------------------------

Step "Clearing the old commits off this machine"

Git-Run reflog expire --expire=now --expire-unreachable=now --all | Out-Null
Git-Run gc --prune=now --quiet | Out-Null

# --- show that it worked ----------------------------------------------------

Step "Done"

$version = '(could not read versions.json)'
$vfile = Join-Path $root 'web\assets\versions.json'
if (Test-Path $vfile) {
    try { $version = (Get-Content $vfile -Raw | ConvertFrom-Json).suite } catch { }
}

$tagCount = ((Git-Run tag).Output | Where-Object { $_ }).Count

Say "On the published history:  $now"
Say "Suite version:             $version"
Say "Tags present:              $tagCount"
Say ""
Say "Restart WD Wireless Tools and it will come up on this version."
exit 0
