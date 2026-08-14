# WD Wireless Tools Backlog

Only unfinished product work belongs here. Completed work is tracked by Git history and GitHub Releases.

Priorities: **P1** = blocking · **P2** = wanted · **P3** = future enhancement.

Last reviewed against v2.0.1.

## P2 — Cloud Manager: bulk merge many folders into one

The current merge workflow accepts one local source folder and one destination. Add a bulk action that accepts multiple selected local source folders, previews the combined file operations, preserves per-file exclusions, and executes each source safely against one destination.

Cloud-to-cloud merging should remain unsupported unless Ekahau provides a safe server-side operation. This feature needs dry-run coverage and file-count verification because source-folder cleanup can be destructive.

## P2 — Cloud Manager: manual External override

Automatic External detection uses project ownership metadata. Add a persistent per-project override so a user can mark a project as External or Mine when ownership metadata is missing or does not reflect operational responsibility.

The dashboard counts, filters, and row styling must all honor the same override. The final UI—row action, inline control, or settings list—still needs a design decision.

## P3 — Report: Change / Audit report

The gallery card exists but is intentionally marked **Coming soon**. Completing it requires:

- A second `.esx` file picker for before-and-after projects.
- AP matching and change classification for added, removed, moved, re-aimed, and re-mounted APs.
- Before/after summaries, change tables, and per-floor overlay rendering.
- Tests for dual-file state, matching thresholds, and generated output.

This is the largest remaining Report feature and should be developed separately from routine maintenance.
