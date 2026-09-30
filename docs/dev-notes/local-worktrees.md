# Local worktrees - the full procedure

Moved out of `CLAUDE.md` on 2026-09-30. This applies to sessions on his Windows
machine, where several sessions share one repository. A cloud session is its own
disposable clone and needs none of it. `CLAUDE.md` keeps the rules; this file
keeps the commands and the incidents behind them.

## Every session gets its own worktree

**Do not work directly in the shared checkout.** Several sessions run against
this repository at once, and until 2026-09-17 they all shared one working tree,
one index and one HEAD. Every incident of that day traces back to that single
fact:

- a session went to stage its own CSS and found `HEAD` already contained it,
  because another session had committed the file out from under it
- a documentation-only commit run with no pathspec swallowed another session's
  fully staged work - fifteen files and a version bump - and published it under
  a message saying no version bump was needed
- `v2.103.14` landed on somebody else's commit, because `main` moved between
  the push and a bare `git tag`
- `v2.102.0` shipped dead, because a module was present in the shared tree and
  untracked, so the local suite passed and CI did not
- uncommitted routing edits sitting in the shared tree failed CI for a session
  that had not touched them
- a session left a landmine where a plain `git add` would have reverted three
  version numbers
- and the clean-slate operation itself opened with `tools/cloud_manager.py`
  holding another session's stale work-in-progress, six lines of committed code
  behind the tree it was sitting in

Each of those has a rule written against it elsewhere in this file - name the
SHA, name the paths, content-based staging. Those rules exist because the tree
is shared. Stop sharing the tree and most of them stop being load-bearing.

**Permanent reusable "slot" worktrees were tried and rejected on 2026-09-29.**
Six fixed worktrees per repo, to get round the desktop app's one-session-per-
folder lock. Safe here, because this repo commits its guardrails, but not in
WaxFrame Professional, whose `CLAUDE.md`, `.confidential-terms` and
`.claude/launch.json` are gitignored: a worktree starts without them, and its
confidentiality check passes with no term list to check against. He chose the
same arrangement in every project over parallelism in one. Do not propose it
again unless that changes.

### Where they live

    C:\wd-worktrees\<session-name>\

**Outside Dropbox, deliberately.** This repository lives inside a Dropbox
folder and a worktree is a full second copy of the tree, so a worktree kept
under the repo gets uploaded and re-downloaded in its entirety, and Dropbox
takes file locks on files git is in the middle of writing.

An earlier draft of this note kept them at `.claude/worktrees/` and suppressed
the sync with an NTFS alternate data stream (`com.dropbox.ignored`). That
works, and it is the wrong shape: it defends against a problem rather than not
having it, and it stays correct only while one invisible attribute survives
every fresh clone, restore and copy. `C:\wd-worktrees` is not Dropbox's
business in the first place. If you find a worktree under `.claude/worktrees/`,
it predates this note - move it.

The directory is created on demand; nothing needs to exist first.

### How to create one

```powershell
git fetch origin
git worktree add -b claude/<session-name> C:\wd-worktrees\<session-name> origin/main
```

Branch off `origin/main`, not off the shared checkout's `HEAD` - the shared
checkout may be mid-edit, and that is the whole problem being avoided. Then
work in there: it has its own index, its own HEAD and its own working files, so
`git add`, `git commit` and `git stash` all become ordinary again.

Two things are still shared and are worth knowing. The **object store** is
shared, which is why this is cheap rather than a second clone. And the **stash
stack** is shared, so a bare `git stash pop` in a worktree can still take
somebody else's entry - prefer a throwaway WIP commit, or `git stash push -m
"<unique tag>"` and `git stash apply <sha>` by id.

### Your copy goes stale while you work, and nothing tells you

**A worktree is only current at the moment it is created.** It is branched from
`origin/main`, which is correct - and from that second onward, every other
session's finished work lands on `main` and yours does not move. Nothing warns
you. No command you run in your own worktree behaves any differently. The copy
you are reasoning about is simply, silently, no longer what is on `main`.

The instruction below - fetch and rebase before pushing - is correct and it is
**late**. It catches the problem at the last possible moment, after all the work
is done, which is the most expensive place to discover that somebody deleted a
module you spent the afternoon calling.

So: **`git fetch origin && git rebase origin/main` at the start of the session,
and again before starting any large change** - not only at push time. Then
re-read this file, because it is the thing most likely to have changed
underneath you, and a stale copy of it is how a session confidently rebuilds
something another session has just deliberately removed.

Measured on 2026-09-19, which is why this is here. One branch held finished work
for thirteen hours while `main` moved five times - a bug fix, a release, two
documentation passes and an edit to this file. Every rebase was clean, so
nothing was lost. What it cost was a version number: two sessions independently
wrote `2.140.0` into `versions.json`, git saw identical bytes and therefore no
conflict, and the collision was caught by eye rather than by any tool. **A
rebase you do early is a rebase against a small difference.** See "The one thing
a worktree does not protect you from" below for the version half of that.

### How work merges back

`main` is still the only branch anybody publishes, and routine work still goes
straight to it - no PR. From inside the worktree:

```powershell
python -m unittest discover -s tests          # green first
git fetch origin
git rebase origin/main                        # not interactive, no editor
python -m unittest discover -s tests          # green again, after the rebase
git push origin HEAD:main
```

The second run is not ceremony. A rebase replays your commits onto code you
have not tested against, and that is exactly how a green branch turns into a
red `main`.

If the push is rejected because `main` moved, fetch and rebase again. Never
force-push `main`. It was force-pushed once, on 2026-09-17, for the history
rewrite, with the repository owner's explicit say-so for that one operation.

Then wait for CI, and tag from the shared checkout as the release process
describes - naming the SHA, as always.

### The one thing a worktree does not protect you from

**Two sessions can pick the same version number, and git will not notice.**

On 2026-09-17 two worktrees bumped `versions.json` from 2.107.0 to 2.108.0
within minutes of each other, for different features. The second rebase applied
cleanly and reported nothing, because both sides had written the *same* bytes -
a conflict needs the two versions to differ. `main` ended up with two unrelated
commits both titled v2.108.0, and the suite version no longer distinguished
them. Nothing was lost and CI stayed green, which is what makes it easy to miss.

A worktree isolates your files. It does not reserve a version number. So before
you bump:

```powershell
git fetch origin
git show origin/main:web/assets/versions.json
```

and bump from *that*, not from what your worktree had when you created it. If
somebody has taken the number you were going to use, take the next one - and if
you only notice after pushing, bump again in a follow-up commit rather than
leaving two changes wearing one number, because the release workflow matches a
tag to exactly one `versions.json`.

### Remove it when you are finished

A worktree left behind is a stale branch, a second copy of the tree, and a
place rule zero material sits unnoticed. From the shared checkout:

```powershell
git worktree remove C:\wd-worktrees\<session-name>
git branch -d claude/<session-name>
git worktree prune -v
```

`git worktree remove` refuses if the tree has uncommitted changes, which is the
correct behaviour - look at what is in there before reaching for `--force`.

**If a teardown ever fails on a perfectly clean worktree**, with:

    error: failed to delete '...': Permission denied

that is not a lock on the contents. Git deletes every file successfully and
then cannot remove the now-empty directory, because something outside git is
holding a handle on it. The registration *is* cleared - `git worktree list`
stops showing it - so the state is half-done while looking finished. Finish it:

```powershell
Remove-Item C:\wd-worktrees\<session-name> -Recurse -Force
git worktree prune -v
```

**Measured on 2026-09-17, and it is the argument for the location.** A worktree
under the repo inside Dropbox failed teardown exactly this way. Three
create-and-remove cycles at `C:\wd-worktrees` - 380 files each - all exited 0
with the directory gone. So the handle was Dropbox's, and moving out of Dropbox
did not merely avoid the sync traffic, it removed the failure. Keep the
`Remove-Item` line anyway: a virus scanner or an open editor can hold a handle
just as well.

**And most often it is your own session holding it.** On 2026-09-18 a teardown
failed this way outside Dropbox entirely, with `Remove-Item -Force` *also*
failing on a directory that was already empty. The holder was a `python.exe`
this session had started itself, hours earlier, as a long-running background
command that never returned - its working directory was inside the worktree,
so an empty folder could not be removed while it lived.

Nothing about that is visible from git, from the error, or from listing the
folder. What finds it is asking which processes are running out of the path:

```powershell
Get-CimInstance Win32_Process |
  Where-Object { $_.CommandLine -like "*<worktree-name>*" } |
  Select-Object ProcessId, Name, CommandLine
```

Stop the ones that are yours - check the command line rather than the name,
for the same reason as `firefox.exe` - and the removal then succeeds. **A
backgrounded command that has not returned is still a live process**, so kill
it before teardown rather than discovering it as a permission error. The dev
toolbar's housekeeping action lists exactly these, which is the other half of
why it exists.

### Prune does not clean up after an abandoned session

**`git worktree prune` cannot see the failure mode that actually happens.**
An earlier version of this note said to prune at the start of every session and
left it there. That instruction is not wrong, it is inert: prune only clears
registrations whose *directory has gone missing*. A session that dies mid-task
leaves the directory sitting there intact, so prune looks straight past it,
exits 0 and prints nothing.

Measured on 2026-09-18, on a worktree created and then abandoned without
teardown:

    git worktree prune -v     # exit 0, no output
    git worktree list         # still lists it
    Test-Path <dir>           # still True

So a green prune at session start is not evidence that `C:\wd-worktrees` is
clean. On 2026-09-18 that folder held six entries: three live, and three that
several sessions had each reported removing on completion. Nothing had errored.
The teardown step simply never ran, and prune could not tell anyone.

**Reconcile the directory against git instead.** At the start of a session, and
again when you finish:

```powershell
git fetch origin
git worktree prune -v
foreach ($d in Get-ChildItem C:\wd-worktrees -Directory) {
    $reg  = (git worktree list) -match [regex]::Escape($d.Name)
    $age  = (New-TimeSpan -Start $d.LastWriteTime).TotalHours
    "{0,-22} registered={1,-5} idleHours={2:N1}" -f $d.Name, [bool]$reg, $age
}
```

Anything idle for hours is a candidate. Anything **not registered** is not a
worktree at all and no git command will ever clean it - see below. Do not
delete another session's work on a timer: confirm it is finished before
removing it, then tear it down properly. `git branch -d` (not `-D`) is the
check that matters - it refuses unless the branch is merged, so a clean
`-d` is your evidence the work shipped.

### `C:\wd-worktrees` holds worktrees and nothing else

Two of the six entries found on 2026-09-18 - `manual-review` and
`ux-sweep-work` - were **not worktrees**. They were ordinary folders a session
had created next to the real ones to hold screenshots, audit scripts, browser
profiles and a draft commit message. `git worktree list` never showed them,
`git worktree remove` did not apply, and prune had nothing to prune. They were
invisible to every step of this convention while sitting in the middle of it.

Session scratch goes in your scratchpad or inside your own worktree, where it
leaves with the worktree. If you put a loose folder or a stray `.txt` in
`C:\wd-worktrees`, nothing in this file will ever clean it up and it becomes
David's problem on his own C: drive - and see the rule below, which covers
every other place this has gone wrong.

**Report what you found and removed rather than cleaning quietly** - rule zero
material has sat in exactly these forgotten corners before.

