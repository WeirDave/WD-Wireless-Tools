#!/bin/bash
#
# What a cloud session has to be told before it can do anything useful here.
#
# Two things, and both of them were costing every session real time:
#
#   1. The suite will not run out of the box. This container's system Python
#      has no flask, and installing into it fails against a debian-managed
#      `blinker`, so every session was discovering that and hand-rolling a venv
#      before it could run a single test. CLAUDE.md documented the workaround;
#      documenting a workaround is not the same as not needing one.
#
#   2. `main` moves while a session works, and nothing says so. A session is
#      branched from `origin/main` at its first second and is stale from its
#      second one. Two sessions picked the same version number on 2026-09-19
#      because neither had any reason to look.
#
# This REPORTS the second rather than acting on it. Auto-rebasing somebody's
# in-progress work at session start could destroy it, and the real gap was
# never "the rebase is hard to type" - it was that nothing told you it was
# needed.
#
# Remote only. Local sessions run on Windows, have their own worktree
# convention, and already have a working Python.
set -uo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

REPO="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
cd "$REPO" || exit 0

# Outside the repository on purpose: several tests walk the working tree, and
# a few thousand files of site-packages inside it is both slow and a place for
# a scan to trip over something it was never meant to read.
VENV="${HOME}/.cache/wd-venv"

# ---------------------------------------------------------------- dependencies
if [ ! -x "${VENV}/bin/python" ]; then
  echo "Creating the test environment at ${VENV} ..."
  python3 -m venv "$VENV" || echo "WARNING: could not create the venv"
fi

if [ -x "${VENV}/bin/python" ]; then
  "${VENV}/bin/pip" install -q --upgrade pip >/dev/null 2>&1
  if "${VENV}/bin/pip" install -q -r requirements.txt >/dev/null 2>&1; then
    echo "Test environment ready: ${VENV}"
    echo "  run the suite with:  python -m unittest discover -s tests"
  else
    echo "WARNING: pip install failed. Run the suite with an explicit venv;"
    echo "         see the release process section of CLAUDE.md."
  fi
  # Put the venv first so a bare `python` is the one that can import flask.
  if [ -n "${CLAUDE_ENV_FILE:-}" ]; then
    echo "export PATH=\"${VENV}/bin:\$PATH\"" >> "$CLAUDE_ENV_FILE"
  fi
fi

# ------------------------------------------------------------------- staleness
echo
if git fetch origin --quiet 2>/dev/null; then
  BEHIND="$(git rev-list --count HEAD..origin/main 2>/dev/null || echo 0)"
  if [ "${BEHIND:-0}" -gt 0 ]; then
    echo "!! This checkout is ${BEHIND} commit(s) behind origin/main."
    echo "   Other sessions have landed work since this branch point. Rebase"
    echo "   before starting, and again before pushing:"
    echo "       git fetch origin && git rebase origin/main"
    echo "   Then re-read CLAUDE.md - it is the file most likely to have"
    echo "   changed underneath you."
    echo
    echo "   What landed:"
    git log --oneline HEAD..origin/main 2>/dev/null | head -10 | sed 's/^/     /'
  else
    echo "Up to date with origin/main."
  fi

  # The version half. Two sessions writing the same bytes is not a conflict,
  # so git will never raise it - see CLAUDE.md, "The one thing a worktree does
  # not protect you from".
  LIVE="$(git show origin/main:web/assets/versions.json 2>/dev/null \
          | grep -o '"suite"[^,]*' | grep -o '[0-9][0-9.]*' || true)"
  if [ -n "$LIVE" ]; then
    echo
    echo "   origin/main is on suite ${LIVE}. Bump from THAT, never from this"
    echo "   checkout, and never reuse a number another session has taken."
  fi
else
  echo "Could not reach origin; staleness is unknown for this session."
fi
exit 0
