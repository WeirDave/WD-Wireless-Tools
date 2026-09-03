#!/usr/bin/env bash
# install.sh — WD Wireless Tools installer and updater (macOS / Linux)
#
# The counterpart to install.ps1.  Two ways to run it, same script:
#
#   Bootstrap (no install yet):
#     curl -fsSL https://raw.githubusercontent.com/WeirDave/WD-Wireless-Tools/main/install.sh | bash
#
#   Update an existing install:
#     bash install.sh          (from inside the app folder)
#
# It picks its own mechanism rather than asking:
#   git available  -> clone, then fetch + checkout the newest release tag.
#   no git         -> download the release ZIP, verify its SHA-256, install it,
#                     keeping the old folder as a dated backup.
#
# Your settings, cloud session and wall templates live in
# ~/.wd_wireless_tools/ — outside the install folder — so nothing here touches
# your work.  See tools/template_store.py for why that split exists.
#
# The app has an Update button that does the same thing (About -> Update now).

set -euo pipefail

REPO="WeirDave/WD-Wireless-Tools"
CLONE_URL="https://github.com/$REPO.git"
API_LATEST="https://api.github.com/repos/$REPO/releases/latest"

CHANNEL="release"
TARGET=""
NO_LAUNCH=0
METHOD="ask"

while [ $# -gt 0 ]; do
  case "$1" in
    --path)     TARGET="${2:-}"; shift 2 ;;
    --channel)  CHANNEL="${2:-release}"; shift 2 ;;
    --method)   METHOD="${2:-ask}"; shift 2 ;;
    --no-launch) NO_LAUNCH=1; shift ;;
    *) shift ;;
  esac
done

step() { printf '\033[36m%s\033[0m\n' "$1"; }
ok()   { printf '\033[32m%s\033[0m\n' "$1"; }
warn() { printf '\033[33m%s\033[0m\n' "$1"; }
err()  { printf '\033[31m%s\033[0m\n' "$1" >&2; }

have_git() { command -v git >/dev/null 2>&1; }

json_field() {
  # $1 = json, $2 = field. Simple "field":"value" only — all we need here.
  printf '%s' "$1" | grep -o "\"$2\"[[:space:]]*:[[:space:]]*\"[^\"]*\"" \
    | head -1 | sed -E 's/.*:[[:space:]]*"([^"]*)"/\1/'
}

suite_version() {
  local f="$1/web/assets/versions.json"
  [ -f "$f" ] || return 1
  grep -o '"suite"[[:space:]]*:[[:space:]]*"[^"]*"' "$f" \
    | head -1 | sed -E 's/.*"([^"]*)"$/\1/'
}

# Echoes 1 if $1 > $2, 0 if equal, -1 if $1 < $2.
cmp_ver() {
  local a="${1#v}" b="${2#v}" a1 a2 a3 b1 b2 b3
  IFS='.' read -r a1 a2 a3 <<< "$a"
  IFS='.' read -r b1 b2 b3 <<< "$b"
  a1=${a1:-0}; a2=${a2:-0}; a3=${a3:-0}
  b1=${b1:-0}; b2=${b2:-0}; b3=${b3:-0}
  if [ "$a1" -gt "$b1" ] || { [ "$a1" -eq "$b1" ] && [ "$a2" -gt "$b2" ]; } \
     || { [ "$a1" -eq "$b1" ] && [ "$a2" -eq "$b2" ] && [ "$a3" -gt "$b3" ]; }; then
    echo 1
  elif [ "$a1" -eq "$b1" ] && [ "$a2" -eq "$b2" ] && [ "$a3" -eq "$b3" ]; then
    echo 0
  else
    echo -1
  fi
}

validate_tree() {
  local root="$1" expected="$2" f d v
  for f in server.py requirements.txt web/assets/versions.json; do
    [ -f "$root/$f" ] || { err "Downloaded release is missing $f"; return 1; }
  done
  for d in tools web templates docs; do
    [ -d "$root/$d" ] || { err "Downloaded release is missing $d/"; return 1; }
  done
  v="$(suite_version "$root")" || { err "Downloaded release has no readable versions.json"; return 1; }
  if [ -n "$expected" ] && [ "$v" != "$expected" ]; then
    err "Downloaded release says v$v but the tag says v$expected"; return 1
  fi
  printf '%s' "$v"
}

sha256_of() {
  if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | awk '{print tolower($1)}'
  elif command -v shasum >/dev/null 2>&1; then shasum -a 256 "$1" | awk '{print tolower($1)}'
  else return 1
  fi
}

# ---- Resolve where we are working -------------------------------------------
# $0 is "bash" (or a pipe) when curl'd through bash, which is how we tell a
# bootstrap run from an in-folder update.
SCRIPT_DIR=""
IN_PLACE=0
if [ -n "${BASH_SOURCE[0]:-}" ] && [ -f "${BASH_SOURCE[0]}" ]; then
  SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
fi

if [ -n "$TARGET" ]; then
  :
elif [ -n "$SCRIPT_DIR" ] && [ -f "$SCRIPT_DIR/server.py" ]; then
  TARGET="$SCRIPT_DIR"; IN_PLACE=1
else
  TARGET="$HOME/Applications/WD Wireless Tools"
fi

EXISTING=0
[ -f "$TARGET/server.py" ] && EXISTING=1
CURRENT=""
[ "$EXISTING" -eq 1 ] && CURRENT="$(suite_version "$TARGET" || true)"

echo
step "WD Wireless Tools"
echo "  Folder:  $TARGET"
[ -n "$CURRENT" ] && echo "  Version: v$CURRENT"
echo

IS_GIT=0
[ -d "$TARGET/.git" ] && IS_GIT=1

# Decide the mechanism. An existing install keeps what it already uses; only a
# fresh install gets a choice, and only when someone is there to answer.
#
# Unlike Windows — where `winget install Git.Git` is quick enough to offer as a
# step in this flow — the macOS routes (xcode-select --install, Homebrew) are
# slow and intrusive, so a missing git is explained rather than installed.
# The menu goes to stderr so the chosen value is the only thing on stdout,
# which is what makes `METHOD="$(choose_method)"` work.
choose_method() {
  {
    echo
    echo "  How would you like to install?"
    echo
    if have_git; then
      echo "    [1] Git  - tracked checkout, updates take seconds. Git is installed."
    else
      echo "    [1] Git  - tracked checkout, updates take seconds. Needs git first:"
      if [ "$(uname -s)" = "Darwin" ]; then
        echo "             xcode-select --install   (or: brew install git)"
      else
        echo "             install git with your package manager"
      fi
    fi
    echo "    [2] ZIP  - no dependencies, each update re-downloads the app."
    echo
  } >&2

  while :; do
    printf 'Choose 1 or 2 [1] ' >&2
    read -r choice || choice=""
    case "$choice" in
      ''|1) echo "git"; return ;;
      2)    echo "zip"; return ;;
      *)    warn "  Enter 1 or 2." ;;
    esac
  done
}

if [ "$EXISTING" -eq 1 ]; then
  METHOD=$([ "$IS_GIT" -eq 1 ] && echo git || echo zip)
elif [ "$METHOD" = "ask" ]; then
  if [ -t 0 ]; then
    METHOD="$(choose_method)"
  else
    # Piped through `curl | bash` with no terminal to prompt on.
    METHOD=$(have_git && echo git || echo zip)
  fi
fi

if [ "$METHOD" = "git" ] && ! have_git; then
  warn "Git isn't installed, so falling back to the ZIP method."
  if [ "$(uname -s)" = "Darwin" ]; then
    warn "Install it with 'xcode-select --install' or 'brew install git', then"
    warn "switch over from Menu -> About inside the app."
  else
    warn "Install git with your package manager, then switch over from Menu -> About."
  fi
  METHOD="zip"
fi

if [ "$METHOD" = "git" ] && { [ "$IS_GIT" -eq 1 ] || [ "$EXISTING" -eq 0 ]; }; then
  # ---- git path --------------------------------------------------------------
  if [ "$EXISTING" -eq 0 ] && [ "$IS_GIT" -eq 0 ]; then
    step "Cloning $REPO…"
    mkdir -p "$TARGET"
    git clone --quiet "$CLONE_URL" "$TARGET"
  else
    step "Fetching updates…"
    git -C "$TARGET" fetch --tags --prune origin
  fi

  if [ "$CHANNEL" = "main" ]; then
    REF="origin/main"; LABEL="main"
  else
    REF="$(git -C "$TARGET" tag --list 'v*' \
          | grep -E '^v[0-9]+(\.[0-9]+)+$' \
          | sort -t. -k1.2,1n -k2,2n -k3,3n | tail -1)"
    [ -n "$REF" ] || { err "No release tags found on the remote."; exit 1; }
    LABEL="$REF"
  fi

  if [ -n "$CURRENT" ] && [ "$CHANNEL" = "release" ] \
     && [ "$(cmp_ver "${REF#v}" "$CURRENT")" -le 0 ]; then
    ok "Already up to date (v$CURRENT)."
  else
    # Preserve an in-place edit to a shipped template before it blocks the
    # checkout.  The app reads user templates from ~/.wd_wireless_tools.
    while IFS= read -r line; do
      case "$line" in
        ?M*_walltemplate.json|M*_walltemplate.json)
          rel="$(printf '%s' "$line" | sed -E 's/^.{2,3}//' | tr -d '"')"
          leaf="$(basename "$rel")"
          mkdir -p "$HOME/.wd_wireless_tools/templates"
          if [ ! -f "$HOME/.wd_wireless_tools/templates/$leaf" ]; then
            cp "$TARGET/$rel" "$HOME/.wd_wireless_tools/templates/$leaf"
            warn "  Kept your customized $leaf as a personal copy."
          fi
          git -C "$TARGET" checkout -- "$rel" 2>/dev/null || true
          ;;
      esac
    done < <(git -C "$TARGET" status --porcelain -- templates 2>/dev/null || true)

    step "Checking out $LABEL…"
    git -C "$TARGET" -c advice.detachedHead=false checkout --force "$REF" >/dev/null
    NEW="$(suite_version "$TARGET")"
    if [ -n "$CURRENT" ]; then ok "Updated v$CURRENT -> v$NEW"; else ok "Installed v$NEW"; fi
  fi
else
  # ---- ZIP path --------------------------------------------------------------
  if ! have_git && [ "$EXISTING" -eq 0 ]; then
    warn "Using the ZIP method. Each update re-downloads the app."
    warn "You can switch to git updates later from Menu -> About."
  fi

  RELEASE_JSON="$(curl -fsSL -H 'Accept: application/vnd.github+json' "$API_LATEST")" \
    || { err "Could not reach GitHub."; exit 1; }
  TAG="$(json_field "$RELEASE_JSON" tag_name)"
  case "$TAG" in
    v[0-9]*) ;;
    *) err "GitHub returned an unexpected release tag: ${TAG:-(none)}"; exit 1 ;;
  esac
  VERSION="${TAG#v}"

  if [ -n "$CURRENT" ] && [ "$(cmp_ver "$VERSION" "$CURRENT")" -le 0 ]; then
    ok "Already up to date (v$CURRENT)."
  else
    ASSET="WD-Wireless-Tools-$TAG.zip"
    BASE="https://github.com/$REPO/releases/download/$TAG"
    STAGING="$(mktemp -d "${TMPDIR:-/tmp}/WDWirelessToolsUpdate.XXXXXX")"
    trap 'rm -rf "$STAGING"' EXIT

    step "Downloading $TAG…"
    curl -fsSL -o "$STAGING/release.zip" "$BASE/$ASSET" \
      || { err "Release download failed."; exit 1; }

    if curl -fsSL -o "$STAGING/release.sha256" "$BASE/$ASSET.sha256" 2>/dev/null; then
      step "Verifying SHA-256…"
      EXPECTED="$(awk 'NR==1 && $1 ~ /^[0-9A-Fa-f]{64}$/ { print tolower($1) }' "$STAGING/release.sha256")"
      [ -n "$EXPECTED" ] || { err "Checksum file is malformed."; exit 1; }
      ACTUAL="$(sha256_of "$STAGING/release.zip")" || { err "No SHA-256 tool available."; exit 1; }
      [ "$ACTUAL" = "$EXPECTED" ] \
        || { err "SHA-256 mismatch — expected $EXPECTED, got $ACTUAL. The download was not used."; exit 1; }
      ok "  Verified $ACTUAL"
    else
      warn "  No checksum published for this release; skipping verification."
    fi

    step "Extracting…"
    mkdir -p "$STAGING/extracted"
    unzip -q "$STAGING/release.zip" -d "$STAGING/extracted" \
      || { err "The downloaded release is not a valid ZIP."; exit 1; }

    TREE="$STAGING/extracted"
    KIDS=0; ONLY=""
    for d in "$TREE"/*/; do [ -d "$d" ] && { KIDS=$((KIDS+1)); ONLY="${d%/}"; }; done
    FILES_AT_ROOT="$(find "$TREE" -maxdepth 1 -type f | wc -l | tr -d ' ')"
    if [ "$KIDS" -eq 1 ] && [ "$FILES_AT_ROOT" -eq 0 ]; then TREE="$ONLY"; fi

    step "Verifying contents…"
    NEW="$(validate_tree "$TREE" "$VERSION")" || exit 1
    ok "  v$NEW, all expected files present."

    if [ "$EXISTING" -eq 1 ]; then
      STAMP="$(date +%Y%m%d-%H%M%S)"
      BACKUP="$(dirname "$TARGET")/$(basename "$TARGET").previous-v${CURRENT}-${STAMP}"
      step "Backing up the current install…"
      cp -R "$TARGET" "$BACKUP"
      echo "  $BACKUP"
    fi

    step "Installing…"
    mkdir -p "$TARGET"
    cp -R "$TREE"/. "$TARGET"/
    chmod +x "$TARGET/Start WD Wireless Tools.command" 2>/dev/null || true

    if [ -n "$CURRENT" ]; then ok "Updated v$CURRENT -> v$NEW"; else ok "Installed v$NEW"; fi
  fi
fi

# ---- Dependencies -------------------------------------------------------------
step "Checking Python dependencies…"
PY="python3"
command -v python3 >/dev/null 2>&1 || PY="python"
if ! "$PY" -c 'import flask, waitress, requests, browser_cookie3, cryptography, keyring, PIL' 2>/dev/null; then
  echo "  Installing missing packages…"
  "$PY" -m pip install -q -r "$TARGET/requirements.txt" \
    || warn "  Some packages failed to install. Run the launcher to see details."
else
  ok "  All dependencies present."
fi

echo
ok "Ready: $TARGET"
echo "  Start it with \"Start WD Wireless Tools.command\""
echo

if [ "$NO_LAUNCH" -eq 0 ] && [ "$IN_PLACE" -eq 0 ] && [ -t 0 ]; then
  printf 'Launch it now? [Y/n] '
  read -r answer || answer=""
  case "$answer" in
    ''|[Yy]*)
      if command -v open >/dev/null 2>&1; then
        open "$TARGET/Start WD Wireless Tools.command"
      else
        bash "$TARGET/Start WD Wireless Tools.command" &
      fi
      ;;
  esac
fi
