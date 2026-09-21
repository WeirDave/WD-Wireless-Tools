# Security sweep — 2026-09-21

A night's pass over the whole suite, starting from the four findings the
2026-09-20 audit left open and then going wider. Everything below is either
fixed and shipped in **v2.157.0**, or listed at the end under what was left
alone and why.

**Run v2.157.1.** Update from About → Update, or run the installer again.
Everything below shipped in v2.157.0; v2.157.1 is a test-only follow-up that
stops the suite leaving two folders in `%TEMP%` per run.

Ranked by what could actually have happened, worst first. Nothing here was
found being exploited; several of them needed somebody to hand him a file,
which is an ordinary Monday.

---

## Critical

### 1. Your dependencies were never checked for being current — only for existing

**What could have happened.** Pillow is what opens the floor-plan images
inside an `.esx`. Its security advisories are almost all bugs in the image
decoders, which is the category where *opening the file* is the attack — no
clicking, no confirming. Somebody emails you a survey, you drop it on Prep
or PlanTrim, and a crafted image inside it runs code as you.

Both installers checked dependencies like this:

    python -c "import flask, waitress, requests, ..., PIL"

If that worked, they skipped installing anything. So the minimum versions in
`requirements.txt` — which is where the security floor lives — **were never
read by anything**. Not on a fresh install, not on an update, not once. A
Pillow from two years ago passed that check forever.

Measured with `pip-audit`: the floors as they stood allowed **70 known
vulnerabilities across six packages**.

**What I did.** The floors are raised to the oldest release with nothing
outstanding against it, checked with `pip-audit` rather than picked by eye.
A new `tools/deps.py` compares what is installed against them; both
installers run it and now upgrade rather than merely install; and the server
says so in the log at startup if an install has drifted since.

**Your machine right now is fine** — I checked, everything installed is
current. The hole was that nothing would have told you if it were not.

---

## High

### 2. The updater installed unverified downloads when no checksum was published

**What could have happened.** The updater and both install scripts refuse a
download whose checksum does not match. They did **not** refuse one with no
checksum at all — they printed a warning and installed it anyway. Anybody who
can put themselves between you and GitHub simply serves the ZIP and no
`.sha256` beside it, and the check is skipped. That is code execution on your
machine, through the update button.

In `install.sh` it was worse in a small way: a *dropped connection* while
fetching the checksum landed in the same branch as "no checksum published",
so a flaky network also skipped verification.

**What I did.** Absent and wrong are the same answer now: all three refuse,
and say what to do about it. This also fires when a release's asset build
half-fails, which has genuinely happened here, so the message names the
releases page rather than just reporting a fault.

**Verified end to end**, because you install from this path in the morning: I
drove the real updater against the real published v2.156.0 — downloaded,
checksum verified, extracted, contents validated, previous copy kept,
installed. Every recent release carries its `.sha256`, so nothing about your
morning changes.

### 3. Four more places where a name could run as code

The v2.146.1 fix covered 25 of these and its guard pinned one exact shape.
Four more were the same bug written differently, and the guard could not see
any of them. All four are fixed and driven in Firefox, Chrome and Edge.

The one that mattered most: **a wall type's id, read straight out of an
`.esx`**, went into two buttons on Quick Walls' wall audit with no escaping at
all. A crafted project file runs code when that panel draws.

The other three come from things you are handed rather than things you type:

- **Squirrel → Rename, saved profile names.** The Apply and Delete buttons
  were escaped with an expression that looks thorough and misses the
  ampersand, so a name containing `&quot;` becomes a real quote when the
  browser reads it and the code after it runs. Profile names travel in a
  settings backup, which is a file somebody can give you.
- **Squirrel → Rename, the token bar.** A token is a *column header from a
  CSV you imported*. It was escaped for text rather than for code, which
  leaves the apostrophe alone.
- **Cloud Manager's share recipients** — the chips, the recent list and the
  suggestions — had the ampersand bug in three places.

**What that would have given an attacker.** Script running inside the page has
the same access the page has: your Ekahau session, the ability to delete
cloud projects, and the update endpoint.

**Proof rather than reading.** I rendered each control with the real function,
pulled the handler back out of the rendered HTML, clicked it, and watched a
flag get set. Then I put each bug back and confirmed the new tests go red in
all three browsers.

### 4. `housekeeping_stop` would kill any process on the machine

**What could have happened.** The dev toolbar's stop endpoint took whatever
process ids arrived in the request and passed each one to `taskkill /F`. No
check that the id was one of ours, or still the same process. Windows reuses
process ids, so a page holding ids from an old survey could kill your browser
with a day of tabs in it, Ekahau with unsaved work, or a system service.

Its neighbour, the clean-up sweep, does the opposite and says so in its own
notes: *"the list is re-derived, not trusted"*. This one action was outside
that rule.

**What I did.** The same rule now: every id is looked up in a fresh survey and
must still be one of ours. Anything else is skipped and reported, rather than
quietly doing nothing.

Worth knowing: no button in the app has ever called it. It was an unused
endpoint offering an unbounded capability.

---

## Medium

### 5. A company logo uploaded as a report cover could run code

An SVG is a document, not just a picture, and the report cover accepts SVG
deliberately — most logos are one. The server handed it back with nothing
stopping the script inside it. Through the `<img>` the report uses, that
script never runs; opened at its address directly, it does, with full access
to everything the app can reach.

A logo handed over by a client and used as a report cover is an ordinary
thing to do, which is what makes this worth fixing rather than noting.

**What I did.** That one response now carries a policy that permits no script,
no network and no framing, and puts the document in its own sandbox. It still
renders as a cover image exactly as before.

### 6. The clean-up sweep guarded the wrong folder

`refused_roots()` — the list of places the sweep must never delete from — was
built from the default user directory rather than from the one actually in
use. With `WD_USER_DIR` set, which is how every automated run isolates itself,
it protected a folder nobody was using and left the live one unlisted. The
override normally points inside `%TEMP%`, which is one of the three folders
the sweep *is* allowed to delete from, so the failure pointed toward deleting
a live settings directory.

The test meant to catch this could not see it: it matched four exact spellings
and the code used a fifth. That check is rewritten to hold the property — no
shipped module names that directory at all — and the sweep's refusal list has
its own test now.

### 7. A settings backup could write outside the user directory

The import guard asked whether the target path *started with* the user
directory's text. A sibling folder whose name begins the same way passes that:
an entry naming `../.wd_wireless_tools_elsewhere/x` lands outside and was
written. A settings bundle is a file somebody can hand you — it is how a
setting gets from home to work — so this is reachable through an ordinary
feature.

Fixed by comparing path *components* instead of characters. The same spelling
was in the release-archive guard; another pass found and fixed that one
independently in v2.156.0, and both now follow one written rule
(`tools/safe_path.py`) with a test that they agree.

### 8. The dev panel's destructive actions had no server-side lock

The dev password is checked entirely in the browser, and `wd-dev.js` is honest
about what that is worth. The server checked nothing, so anything running
inside a page — including script from a crafted `.esx` — could call the
clean-up sweep and the process stop directly.

**What I did, and what I deliberately did not.** The two actions that *write*
now need the password proved to the server, once per run of the server.
Entering dev mode through the password box does that at the same time, so your
normal route is unchanged; via `?dev=1` you get asked once, at the moment you
press a delete button.

The survey is **not** behind it. It is a read, it returns counts rather than
values, and charging a password for it would be the kind of guard that fires
on your normal case.

I did not put a lock in front of `/api/cloud/*` or `/api/update`. Those can
delete cloud projects and install code, and locking the dev panel while
leaving those open would be theatre. What protects those is the rule the audit
already established — every destructive action re-derives its target on the
server before it writes — and that is now true of the process stop too.

### 9. Release notes published your commit messages

Not a way in, but it publishes things about you. Commit messages here quote
you directly and describe what you were working on; that is right for the
record and wrong for a public page. The release workflow pasted the commit
message in as the note, and the documented fix was to replace it by hand every
time. That does not work — 58 of the first 60 went out as commit messages, and
an audit found 34 of the 60 published notes quoting you.

The automatic note is now a short factual stub naming the version and linking
to the commit. Your hand-written note still replaces it the same way. One line
to revert if you disagree.

---

## Low

### 10. Download filenames were pasted into a header unescaped

Three download routes built `Content-Disposition` by dropping a project name
straight in. A quote in the name ended the field early. It also meant an
accented project name could not travel at all — the header came back mangled
or dropped. Both fixed by one helper.

### 11. No limit on how large a request could be

Four routes read an entire upload into memory before looking at it. There is a
1 GB ceiling now, set about five times above the largest project seen here so
it cannot fire on a real one, and it answers in words rather than with a blank
page.

### 12. A crafted `.esx` could exhaust memory

A few hundred kilobytes of archive can hold gigabytes of zeroes, and the first
thing that happened was reading it all. Uploaded archives are now checked
against sane ceilings — total size, single-member size, member count, and
expansion ratio — before anything is read. The limits are far above any real
project; the largest seen here is inside every one of them by an order of
magnitude.

### 13. A release built by hand could have packaged stray files

The release builder walked the folders on disk, so anything untracked sitting
in `tools/`, `web/`, `templates/` or `docs/` went into the ZIP — a screenshot,
a scratch file, a project somebody dropped in to reproduce something. CI builds
from a clean checkout so this never bit, but a ZIP asset is the one published
thing that cannot be edited afterwards. The payload is what git tracks now.

### 14. Small hardening, no known route in

- `X-Content-Type-Options: nosniff` on every response.
- The release workflow's first job no longer inherits a write token it never
  uses.
- `explorer /select,` refuses a path containing a quote. Not reachable —
  Windows forbids that character in a filename — but the reasoning that made
  it safe rested on a filesystem rule rather than on anything the code did.
- Four files had grown their own private escaping functions, one of which
  disagreed with the shared one. They all delegate now, so `esc` means the
  same thing everywhere.
- Setup's subfolder summary rendered names unescaped.

---

## What I looked at and left alone

**`/api/report/open_esx` reads any `.esx` on the disk.** The path comes from
the browser. This is deliberate and the code says so: Report parses the archive
in the browser and the native picker gives back a path. Locking it down would
break "open from disk". Worth knowing it exists, because script inside a page
could use it to read a project you did not open.

**The whole API trusts same-origin.** That is the architecture of a
localhost tool and I have not changed it. Cross-site is properly closed — the
server rejects a foreign Host, a foreign Origin, and any state-changing
request without a custom header that a form cannot set. What it cannot
distinguish is script that gets *into* one of its own pages, which is why the
injection work above is the thing that actually matters.

**GitHub Actions are pinned to tags, not commit hashes.** A compromised tag on
a third-party action would run in your CI. Every action used here is
GitHub's own, and pinning by hash means updating them by hand forever. I
judged that trade not worth it for a one-person repository; say the word and
it is a small change.

**No Content-Security-Policy on the tool pages themselves.** A real one would
make injected script much harder to use, and every control in this suite is
wired with an inline `onclick` — so a policy strict enough to help would need
all nineteen pages converted first. That is a project, not a night's work, and
it is the single biggest remaining improvement.

**Your cookie store is in good shape.** Encrypted with a key in the Windows
credential vault, written atomically with owner-only permissions, never
recreated in plaintext if anything fails, and correctly excluded from settings
exports. I found nothing to fix. The log file carries no credentials either.

---

## How this was checked

Full suite green on a clean clone of `main` before starting (2,843 tests) and
green again on a clean clone of the finished commit (3,048). Every guard added
was mutation-checked: the bug put back, the test watched going red, the fix
restored. The browser work was driven in Firefox, Chrome and Edge, not read.

The dev gate is checked against a **real running server** in all three
browsers, because its two halves are separately correct and the interesting
question is whether they are joined — a gate whose password box works and
whose server works, with nothing between them, is a toolbar that asks for a
password and then refuses everything. That test copies the tree to a scratch
folder, points `WD_USER_DIR` at a throwaway directory and neutralises the
browser-window spawn, so it cannot reach anything of yours and leaves no
Firefox behind.

No assertion in any new test checks that a source file merely *contains*
something — the suite's own ratchet holds that, and it caught two of mine,
which is why they were rewritten to assert on parsed structure instead.

Two of my own mistakes are worth recording because the repository already warns
about both: a patch script wrote a literal backspace byte instead of `\b`, and
a probe sliced a *comment* quoting the old code instead of the code — which
would have passed against nothing. Both were caught by checking the output
rather than the exit code.
