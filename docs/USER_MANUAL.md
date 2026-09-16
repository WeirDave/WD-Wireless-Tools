<div align="center">

<img src="../web/assets/wd-wireless-tools-v8.0-720x720.png" alt="WD Wireless Tools" width="150">

# WD Wireless Tools

## User Manual

**Practical guidance for the complete Ekahau workflow suite.**

![Local First](https://img.shields.io/badge/local--first-private-5fa970?style=flat-square)
![No Telemetry](https://img.shields.io/badge/telemetry-none-5fa970?style=flat-square)
![Platforms](https://img.shields.io/badge/platform-Windows%20%7C%20macOS-6b7280?style=flat-square)

[Home](../README.md) · [Project Page](https://weirdave.github.io/WD-Wireless-Tools/) · [Latest Release](https://github.com/WeirDave/WD-Wireless-Tools/releases/latest) · [Get Help](https://github.com/WeirDave/WD-Wireless-Tools/issues)

</div>

<table>
<tr>
<td width="20%" align="center"><img src="../web/assets/cloud-manager-v8.0-560x560.png" alt="Cloud Manager" width="90"><br><b>Cloud Manager</b></td>
<td width="20%" align="center"><img src="../web/assets/quick-walls-v8.0-560x560.png" alt="Quick Walls" width="90"><br><b>Quick Walls</b></td>
<td width="20%" align="center"><img src="../web/assets/squirrel-v8.0-560x560.png" alt="Squirrel" width="90"><br><b>Squirrel</b></td>
<td width="20%" align="center"><img src="../web/assets/scale-v8.0-560x560.png" alt="Scale" width="90"><br><b>Scale</b></td>
<td width="20%" align="center"><img src="../web/assets/report-v8.0-560x560.png" alt="Report" width="90"><br><b>Report</b></td>
</tr>
</table>

---

## Contents

- [Start Here](#start-here)
- [Install and Launch](#install-and-launch)
- [Home and Navigation](#home-and-navigation)
- [Cloud Manager](#cloud-manager)
- [Quick Walls](#quick-walls)
- [Squirrel](#squirrel)
- [Scale](#scale)
- [Report](#report)
- [AP Labeler](#ap-labeler)
- [PlanTrim](#plantrim)
- [Capacity](#capacity)
- [Prep](#prep)
- [Suite Settings](#suite-settings)
- [Data, Privacy, and Security](#data-privacy-and-security)
- [Update or Uninstall](#update-or-uninstall)
- [Troubleshooting](#troubleshooting)
- [Getting Help](#getting-help)

---

## Start Here

WD Wireless Tools is a local suite for common Ekahau workflows. It runs on Windows and macOS and opens in your normal browser, but everything executes on your own machine — nothing is uploaded.

| If you need to… | Use | Available |
|---|---|---|
| Compare local projects with Ekahau Cloud | Cloud Manager | Desktop |
| Remap wall types or apply wall templates | Quick Walls | Desktop |
| Organize loose project files | Squirrel | Desktop |
| Convert architectural measurements | Scale | Desktop |
| Generate installer-ready documents | Report | Desktop |
| Label access points with a naming pattern | AP Labeler | Desktop |
| Trim excess whitespace from floor plans | PlanTrim | Desktop |

> **Before working on production files:** retain a backup and review every preview before a bulk rename, move, delete, or Cloud operation.

## Install and Launch

### Requirements

- Windows or macOS
- Python 3.10 or newer for the complete desktop suite
- Chrome, Edge, or Firefox signed into Ekahau Cloud for Cloud Manager

Python is required for every tool in the suite.

### Install the desktop suite

1. Open the [latest GitHub release](https://github.com/WeirDave/WD-Wireless-Tools/releases/latest).
2. Under **Assets**, download `WD-Wireless-Tools-vX.X.X.zip`. Do not choose GitHub's automatically generated “Source code” archives.
3. Extract the ZIP to a permanent folder.
4. On Windows, double-click `Start WD Wireless Tools.bat`. On macOS, double-click `Start WD Wireless Tools.command`.

The launcher installs any missing Python packages on first run, starts the local service, and opens [http://localhost:8675](http://localhost:8675). Keep the terminal window open while using the suite.

> **macOS first launch:** if Gatekeeper blocks `Start WD Wireless Tools.command`, right-click the file, choose **Open**, and confirm **Open** once more.

### Launch manually

```bash
pip install -r requirements.txt
python server.py
```

## Home and Navigation

The home page displays the five tools and their installed versions. Select a card to open a tool. The shared menu lets you:

- move between tools;
- open the current tool's built-in guide;
- switch between light and dark themes; and
- check suite and component versions.

Browser Back returns to the prior page. The WD Wireless Tools mark returns to the suite home when it is presented as a navigation control.

---

## Cloud Manager

Cloud Manager compares projects in Ekahau Cloud with local `.esx` files and provides deliberate, preview-driven project-management actions.

### First-time setup

1. Sign into Ekahau Cloud in a normal Chrome, Edge, or Firefox window.
2. Open **Cloud Manager** from the suite home.
3. If prompted, select **Log in to Ekahau Cloud**, complete the login in the browser tab, and return to Cloud Manager.
4. Choose the local parent folder containing your Ekahau project folders.

Safari, Brave, Arc, and Private/Incognito windows are not supported for automatic session discovery.

### Understand the main view

- **Cloud rows** represent projects available to your signed-in Ekahau tenant.
- **Local rows** represent `.esx` files beneath the folder you selected.
- Match indicators and character-level differences help verify whether names refer to the same project.
- The **Duplicates** view groups near-duplicate files and identifies useful comparison details such as newest and largest.
- The **≈** indicator jumps from a project row to its duplicate cluster.

### Who you are seeing — the Owner filter

The **Owner** toggle in the toolbar switches between **All**, **Mine** and
**Others**. It lasts until you reload the page and nothing in the toolbar is
written to disk.

What the list *opens* on is a separate, saved setting: **Suite Settings →
Cloud → Default view**. It ships as **All**.

These are deliberately two different things. A per-browser memory of the filter
is how one machine came to show three sites and another twenty — so any filter
narrower than All prints a line above the list saying what is hidden and whether
that is your saved default or just this visit, an empty list names the filter
that emptied it, and a sign-in that returns no user identity turns the filter
off and says why.

### Which side is newer

A matched pair whose two copies differ in age carries a badge:

- **⇩ Cloud newer · download** — the cloud copy was edited more recently. Click
  the badge to bring it down over your local file. Your current copy is kept
  beside it as a `.previous-<timestamp>.esx`.
- **⇧ Local newer** — your copy is the newer one. **Sending it up is not built
  yet.** The upload this tool has creates a *new* cloud project rather than
  replacing the one already there, so the direction is a job still on the list
  rather than something Ekahau forbids. Nothing is at risk in the meantime:
  sync never replaces the newer side with the older one. Open the project in
  Ekahau and save it to the cloud from there — that is where Ekahau's own
  sync-or-overwrite prompt lives.

The download is only offered for a pair that is **proven** or that you linked
yourself. A pair matched on name similarity alone says so and offers the 🔗
button to confirm the link, which makes the download available. Overwriting a
file on a guess is how the wrong project gets lost.

### Sync everything

**⇅ Sync everything** needs no selection, which is the point. It works out for
each file which side is newer and does that, or nothing when the two already
match, and shows the whole plan before it runs. It never replaces a newer file
with an older one. When it finishes it says where local and cloud stand,
including anything still waiting to go up.

### Move projects into a site

Select any number of projects — on either the **Projects** tab or among the
nested files on the **Sites** tab — and choose **Move to site…**. The picker
confirms a destination per row, auto-filled where the site is recognisable, and
each move is queued as its own card with its own retry. A project whose local
and cloud copies are matched moves **both** sides, so the pair survives the
move.

### Share a project with people

**Menu → Manage Sharing** on a project, then the **Share with someone** box.

**Add several people at once.** Separate addresses with a **comma, a semicolon
or a space**, or paste a list — any of those, mixed in any combination. A list
copied out of Outlook works, including the `Name <address>` form; the names are
dropped and the addresses kept. Each address becomes its own removable tag, so
correcting a typo means clicking the × on that one rather than editing a long
line of text. Backspace in an empty box takes back the last one.

Choose the role once in the dropdown beside the box — it applies to everyone
you add in that go. It defaults to **View only**, and external addresses always
arrive as View only regardless, because Ekahau limits write access to people
inside your organisation.

**One bad address does not throw away the good ones.** Anything that is not a
valid address is outlined in red and left in place for you to fix. Everyone
else still goes through, and the result is reported **per person** — so if one
address bounces you are told which one, and the people it worked for are
genuinely shared. Any address that failed stays in the box so you can correct
it and try again.

**It remembers who you have shared with.** Start typing and matching addresses
appear beneath the box; arrow keys and Enter pick one. A **Recent** row under
the box offers the last few directly. To drop someone from that list, click the
× beside their name in the Recent row — it removes them from the suggestions
only and changes nothing about who has access to anything.

Only addresses that a share actually succeeded for are remembered, so a typo
is never offered back to you.

**This list stays on your computer.** It lives with your other settings, in
`%USERPROFILE%\.wd_wireless_tools\share_recipients.json`, and is never sent
anywhere. It is included in **Settings → Export settings**, so rebuilding a
machine does not mean rebuilding the list from memory.

### Buttons that are greyed out

The toolbar's bulk buttons switch on and off with what you have selected.
**Click a greyed-out one and it tells you what to select** — hovering says the
same thing. A dimmed "Compare" answers "Select 2+ local folders to compare"; a
dimmed "Share…" explains that Ekahau only lets a project's owner add shares.

### Perform an operation

1. Filter or search until the intended projects are visible.
2. Select the relevant rows.
3. Choose the upload, download, rename, move, merge, or delete action.
4. Read the preview and confirm the exact source, destination, and number of affected items.
5. Start the operation and review its completion status.

Use **Show in Explorer/Finder** to verify a local file directly before acting on it.

> **Cloud actions are real actions.** A clean preview is your last checkpoint before a rename, move, overwrite, or deletion reaches the selected files or tenant.

**Deleting anything on the cloud side asks twice**, and the second time you type
`DELETE` before the button will enable. Local deletes do not, and the difference
is deliberate: a local file you can download again, a cloud project you cannot.
That applies to a single row and to a bulk delete alike. Selecting one side of a
matched pair deletes only that side.

### Login storage

Cloud Manager stores an encrypted copy of the active Cloud session under `~/.wd_wireless_tools/`. Its encryption key is stored separately in Windows Credential Manager or macOS Keychain. Use **Menu → Forget Cloud Login** to remove the saved session and key.

### Implementation note

The `EkahauAPI` client in `tools/cloud_manager.py` includes reverse-engineered request flows required for operations performed by the Ekahau web application, including presigned uploads and client-side `.esx` download assembly. This is application code. A local `.claude/` directory is development-tool configuration and is not required or distributed.

---

## Quick Walls

Quick Walls edits wall types inside an Ekahau `.esx` project without uploading it.

### Remap walls

1. Drop an `.esx` file onto the page, or select the drop area to browse.
2. Review every wall type detected in the project.
3. Choose a replacement for each type you want to change.
4. Review the mapping, then save the updated `.esx`.

### Wall heights

A wall type can be given a height, so a partial-height obstruction is modelled
as one rather than as a barrier from the slab to the roof. In **Quick Walls**,
open a wall type and set **Height**:

- **Auto** is the default and means floor to ceiling. It is a real answer, not
  an unset one, and it is what most wall types should stay on.
- **Fixed** takes a number, entered in **feet** when the units toggle is set to
  imperial, and metres otherwise. Thickness is in inches; height is in feet.

The panel says how many drawn segments the change affects, because **height
belongs to the wall type, not to an individual segment** — changing it changes
every wall already drawn with that type.

> **The shipped template only sets a height where the name says one.**
> `Walls, Steel 12ft` is 12 ft and `Warehouse Rack Wall - 16ft` is 16 ft. Every
> other type ships on Auto, including `Warehouse Rack Wall`, `Cubicle` and
> `Bookshelf` — a guessed height changes every project that opens the template,
> silently, in a direction nobody chose.

### Does this one reach the ceiling?

When a project is open, a panel above the wall list asks about any wall type
that is **set to Auto and describes something standing on the floor** — racking,
shelving, cubicles. Auto means Ekahau models it from the slab to the roof, which
is right when the racking really does run to the deck and wrong when it stops
short, and nothing in the file records which building you have.

Each row names the type, how many segments are drawn with it, and its
attenuation. Three answers:

- **Set to N ft** writes the suggested height onto the wall type.
- **Edit…** opens the type so you can enter your own.
- **It does reach** leaves it on Auto and stops asking for as long as the
  project is open. Nothing is written — Auto is already what it says.

The panel disappears when there is nothing to ask about.

### Use templates

- Apply an included Ekahau or WD template to create a mapping quickly.
- Save a custom mapping as a reusable JSON template.
- Configure a default template when you want it proposed automatically on file open.
- Use number keys `1` through `9` when working with the corresponding wall-picker positions.

Custom templates are saved under `~/.wd_wireless_tools/templates/`, outside the application folder, so updating the suite never touches them and they are the same whichever browser you open the tools in.

**Applying a template adds; it never removes, and it never restyles a wall type
Ekahau ships.** A type the template carries is added, or updated if you added it
yourself. A type the template says nothing about is left alone, so walls already
drawn with it still resolve. And a type that is part of Ekahau's standard set is
left exactly as Ekahau ships it — the toast names the ones it left alone rather
than going quiet about them.

That last rule exists because a template saved out of a project carries whatever
that project had, including a colour somebody changed once. Until v2.100.5,
applying the shipped template recoloured three standard types in every project
it touched, and said nothing.

To put a standard type *back*, pick **Ekahau Defaults** in the Template dropdown
and press **Apply** — restoring the standard values is what that one is for.
The **Ekahau Defaults** *button* further along the bar is a different thing: it
replaces the whole list, names what it will remove, and asks first.

---

## Squirrel

Squirrel organizes loose Ekahau project material into consistent project folders.

### Organize a folder

1. Choose the folder you want to scan.
2. Review discovered projects, classifications, and proposed destinations.
3. Adjust exclusions, naming rules, or destination folders as needed.
4. Confirm only when the preview matches your intended structure.
5. Review the completion summary.

Squirrel can classify `.esx` files, images, floor plans, and reports; create project folders; apply naming rules; find duplicates; and undo supported organization operations.

Classification follows the extensions and keywords in **Suite Settings →
Squirrel**: `.dwg` and the other plan types go to `floorplans/`, images to
`images/`, and reports to `reports/`. The `.esx` itself stays where it is — it
is the project, not material belonging to one.

**Undo puts everything back.** After an organize run, Undo restores every file
to where it came from, and the menu says how many moves are available to undo.

> Start with a small representative folder if you are introducing new naming rules. Once the preview is right, apply the same rules to the larger collection.

### Rename

**Squirrel → ▸ Tools → "· Rename…"** renames folders or files in bulk. Three
tabs, each with its own preview and its own Undo:

- **Folders** — build a folder name from a format string using tokens like
  `{site_code} - {site_name}`. Values come from a CSV you load, or you type them.
- **Files** — the same idea for filenames, with `{original}` available for the
  part you want to keep.
- **Rules** — no format string; strip a prefix or suffix, apply a regex,
  normalise the separator, or force a case.

Nothing happens until the preview looks right: **Apply Rename** stays greyed out
until the preview contains at least one item that would actually change, and the
preview names anything it would skip — already correct, unmatched, or a
collision with a name that already exists.

Your format strings and rules are remembered and come back the next time you
open the page.

> **They did not, before v2.100.x.** The page saved them to an endpoint that
> did not exist, and the reply was never checked — so every setting on this page
> was silently discarded the moment you left it, while the page went on loading
> them back on arrival, which is what made it look like it remembered. The
> renames themselves were always performed correctly; only the settings were
> lost.

---

## Scale

Scale converts architectural measurements between feet-and-inches, decimal feet, inches, meters, and millimeters.

1. Enter a value on either the imperial or metric side.
2. Review the synchronized conversions.
3. Select the copy control beside the value you need.

Supported architectural formats include `4' 6-1/2"`, `4' 6 1/2"`, and `1/2"`. A bare number is treated as feet on the imperial side and meters on the metric side.

---

## Report

Report turns an Ekahau `.esx` project into print-ready handoff documentation.

### Build a report

1. Select **Open from disk** to browse for an `.esx`, or drop one onto the page.
2. Choose a report template.
3. Configure sections, AP filters, label style, units, and template-specific options.
4. Add a logo when the document requires customer or company branding.
5. Review every generated page.
6. Use the browser print dialog to print or save the result as PDF.

**The saved file name includes the project.** It comes out as
`Report - <template> - <revision> - <project>`, where the project is the name of
the **folder the `.esx` was opened from** — that folder is usually the job
itself (client, building, address) while the file inside it is named after the
site or the discipline. Opening from disk is what makes the folder knowable; a
dragged-and-dropped file carries only its own name, so the `.esx` file name is
used instead. If the folder name says nothing about the job — `Downloads`,
`Desktop`, `New Folder` — it is skipped in favour of the file name. Report
settings shows the exact name it will offer, with and without the revision.

### Available report templates

- AP Placement Map
- AP Installation
- Antenna Aim Sheet
- Coverage Cell Boundary
- Site Summary Sheet
- Interference / Rogue Devices
- Bill of Materials

The Change / Audit Report appears as **Coming soon** and cannot yet be selected.

Each card says who the sheet is for and how many pages you get, because that is
what separates templates that otherwise look alike.

> **Changed:** *Predictive Design / AP Placement* no longer exists as a separate
> template. Its only real difference from the AP Placement Map was whether large
> floors were split into sections, which is now a checkbox on the map itself.
> Choosing it now opens the AP Placement Map, and any options you had saved
> against it are carried over. You gain per-page orientation, the Key Plan and
> match lines, none of which the old template had.

### Settings that stay set

Every checkbox, radio and dropdown in the report sidebar is remembered, per
template. Configure a report the way you want it and press **Save these as my
defaults** — the next report of that type opens that way.

Changing an option without pressing that button affects only the report in front
of you. The card under the options always says which state you are in, and
**Use shipped defaults** puts a template back to how it arrived.

Client, prepared-by, project reference and revision are shared across every
template rather than saved per template, and live in Report settings.

**Units default to feet** and are remembered for you, not per report. There is
no longer a "show both units" option — a length is shown once, in the unit you
chose. An `.esx` always stores metres internally; this only changes how the
report is written.

### Large floors

A floor too big to read on one sheet can be split into lettered sections. Turn on
**Split large floor plans into zoomed sections**.

- **Section size** controls how much ground one sheet covers, from *More detail —
  smaller sections* through to *Fewest pages — largest sections*. It is
  remembered for you. **Standard** is what the tool has always produced.
- Every section page carries a **Key Plan** — the whole floor in miniature, all
  sections lettered, the one you are looking at filled in.
- **Match lines** mark each edge where the drawing continues, labelled with the
  section that carries on, so a run of racking can be followed page to page.
- **Configure grid…** opens the plan so you can set rows and columns by hand and
  position the area to be covered. Sections containing no APs are drawn dashed —
  they never become sheets.

### AP labels

Floor-plan markers and AP-table labels come from the AP names inside the project. When a name ends in an AP designator such as `SITE-B1-01-AP42`, the short-label option can show `42` for quick map-to-table cross-reference. Turn off **Short number labels on the plan** when full names are preferable.

### AP notes

Notes you record against an access point in Ekahau — mounting caveats, access
problems, anything typed onto the AP — can be printed as their own page.

In **any report**, in the options panel of the **Configure** step, set
**"AP notes pages"**. It is the last control in that panel, directly below
*Compass reference page*, and it offers three choices:

| Choice | What you get |
| --- | --- |
| **Auto** (the default) | The pages appear when the project has notes on its APs, and not otherwise |
| **Always include** | The same, since a floor with no notes contributes no page |
| **Never include** | No notes pages, whatever the project contains |

Your choice is remembered once you press **Save these as my defaults**.

> **Set it to Never on a document you are handing over.** Site notes are often
> your own working annotations — mounting caveats, access problems, things you
> wrote for yourself — and they are not always meant for a client or an
> installer. That is the whole reason this is a separate control rather than
> something tied to another setting.

You get one page per floor, headed **AP Notes**, listing each access point that
has notes and the text of each one. An AP can carry more than one note and all of
them are listed.

> **Text is printed; photographs are not.** A note can have a picture attached.
> Those notes are still listed, with any text they carry, and marked *"Image
> attached — not shown in this report"* — so nothing is silently dropped, but the
> image itself is not printed and there is no option to print it.

The page appears only when at least one access point on that floor actually has
notes, so turning the option on for a project without any changes nothing.

**The notes pages are the last thing in the document**, after the compass
reference page and any label key. That is deliberate rather than incidental: the
section has no fixed length — a survey that photographs every AP would produce a
page per access point — so nothing you might look up by position is allowed to
sit behind it.

### Page orientation

Each page can be set to **Auto**, **Portrait** or **Landscape** using the control
above it, and the choice is remembered. Auto turns a page only when turning it
prints the map meaningfully larger, so a plan that gains little stays upright.

**Mixing portrait and landscape in one document works in Firefox, Chrome and
Edge.** All three have been measured printing a document whose pages ask for
different sheets, and all three give each page the sheet it asked for. You do
not need to make a report uniform to get it to print correctly.

If pages ever do come out clipped at the right-hand edge, that is the symptom of
a page laid out for one orientation printed on a sheet of the other. Press
**Match all pages** on any page to put the whole report one way round, which is
always correct — and worth reporting, because on these three browsers it should
not happen.

### Print cleanly

- Confirm the expected paper size and orientation in the browser print dialog.
- Enable background graphics if your browser offers that option.
- Inspect page breaks, map readability, and table wrapping in the preview.
- Save to PDF and inspect the final PDF before sending it to installers or customers.

---

## AP Labeler

AP Labeler replaces Ekahau's default "Simulated AP-xxx" names with a structured naming pattern you define, then downloads a labeled `.esx` ready to open in Ekahau. Your original file is read but never modified.

### Name pattern

Choose one of three modes:

- **Structured** — build a name from composable segments. Each segment is one of:
  - **Text** — a fixed label (site code, building, department, wing).
  - **Floor** — auto-detected from the `.esx` file. Leave the field empty to use the auto value, or type a custom override.
  - **Counter** — a sequential number with a tag prefix (e.g. `AP`), a configurable start number, and 0–5 leading zeros.
  
  A global **Separator between segments** dropdown sets the character placed between each segment (dash, underscore, dot, space, or none). Add, remove, and reorder segments to match your site's naming convention.

  **The segments arrive filled in.** If the APs in the project are already named
  to a scheme, the file is read and the segments are built from it — site code,
  building, AP prefix, number width and separator — so adding one AP and
  renumbering does not mean retyping a convention the file already states.
  Change anything you disagree with; nothing is committed until you download.

  **What the Floor segment auto-detects.** In order of preference: the floor
  number Ekahau recorded for that floor, then a number found in the floor's own
  name (`01 - Ground`, `Level 2`, `3rd floor`), then the floor's position in the
  list. Hover the box to see which value was picked; type in it to override.

  > Before **v2.99.8** this read only the first of those three, which Ekahau
  > fills in only for floors attached to a building. A project without one had
  > every floor auto-detect as `00`, and with **Per Floor** scope that produced
  > the same set of names on every floor. If you labelled a multi-floor project
  > on an earlier build, check it for repeated names.

- **Simple** — prefix + separator + sequential number with configurable leading zeros and start number.
- **MAC** — names derived from each AP's MAC address.

### Scope

- **All APs** — one continuous sequence across the entire project.
- **Per Floor** — restart numbering on each floor.

### Ordering

Ordering decides the sequence numbers are handed out in, so changing it changes
every name the tool produces.

> **Read this if you have a saved naming template or a numbering scheme you
> expect to match a previous survey.** Two things about ordering are not what
> they were in early versions:
>
> - **Nearest Neighbor is the default.** It walks from each AP to whichever one
>   is closest, the way you would if you were pacing the building. On a real
>   floor plan that follows rooms and corridors rather than the page.
> - **Zigzag Rows means a true zigzag.** It sweeps row by row from the top,
>   reversing direction on every other row, so the walk never jumps back across
>   the building at the end of a row. It used to behave differently.
>
> If you renamed a site under an earlier version and need a new survey to match
> it, check the preview against the existing names before downloading rather
> than assuming the same option gives the same sequence.

The full list:

| Ordering | What it does |
|---|---|
| **Nearest Neighbor** *(default)* | Walks to the closest remaining AP each time |
| **Zigzag Rows** | Rows top to bottom, every other row reversed |
| Rows, Left → Right | Row by row, always left to right |
| Rows, Right → Left | Row by row, always right to left |
| Columns, Top → Bottom | Column by column, downward |
| Columns, Bottom → Top | Column by column, upward |
| Clockwise | Around the plan, clockwise from the top |
| Counter-clockwise | Around the plan, anticlockwise from the top |
| **By Colour Groups** | All of one Ekahau colour, then all of the next |
| Manual (click order) | You click each AP on the plan in the order you want |

The preview shows the resulting names over the floor plan, so the ordering can be
judged by looking at it before anything is downloaded.

### By Colour Groups

Picking **By Colour Groups** numbers every AP of one colour before moving to the
next, using the colour you marked each AP with in Ekahau. Within a colour the
APs are still walked by proximity, so a group is numbered in the order you would
walk it.

Two extra controls appear when it is chosen:

- **The colour sequence list**, under the ordering dropdown. It lists every
  colour actually present in the project, by the name Ekahau uses for it —
  Clear, Yellow, Orange, Red, Pink, Violet, Blue, Gray, Green, Brown, Mint —
  with a count of how many APs carry it. It starts alphabetical. **Drag a row to
  move it**, the same gesture as the wall-type slots in Quick Walls; the number
  beside each row is the order it will be numbered in. An AP with no colour set
  in Ekahau appears as **Clear** and is numbered like any other group.

- **Two tabs above it** decide how colour and floor interleave:
  - **Finish each floor** — floor 1's blues, greens and greys, then floor 2's
    blues, greens and greys.
  - **Colour through building** — every blue on every floor, then every green on
    every floor.

  Choosing **Colour through building** switches **Scope** to **All APs** and
  says so. The two cannot both be true: carrying one colour up through the
  building has already spent the per-floor counter by the time it comes back
  down for the next colour.

### Manual (click order)

Every AP on the floor is drawn, ringed in its own Ekahau colour, so "start with
the blue ones" can be done by eye. Click one to give it the next number. Three
things take a number back:

- **right-click anywhere on the plan**,
- **Ctrl+Z**, or
- **click the numbered marker itself** (its tooltip says so).

**Undo** and **Clear all** buttons above the preview do the same thing. APs you
have not clicked keep their current names and show a `–` in the preview's
number column.

### Preview and download

The preview table shows the first five current→new name mappings with a toggle to expand. Once satisfied, click **Download labeled .esx** to save the renamed file.

Above the table, a line shows what every name on the floor has in common before
and after, so the part that is actually changing is the part you read. The table
itself omits that shared stem from both columns.

**If any two APs would end up with the same name**, an amber line appears above
the preview naming them and suggesting the two fixes — add a **Floor** segment,
or set **Scope** to **All APs** so the counter keeps going instead of restarting
on each floor. It is a warning, not a block: the Download button stays
available, because a name you chose deliberately is your decision. Ekahau will
accept duplicate names, and you will not be able to tell those APs apart
afterwards.

### Templates

Save and load naming patterns as templates. Templates are stored server-side in `~/.wd_wireless_tools/` and persist across sessions and machines.

---

## PlanTrim

PlanTrim removes excess whitespace around floor plan images inside an `.esx` file, reducing file size and improving readability in Ekahau. Drop an `.esx` file, review the proposed crops per floor, and download the trimmed result. Coordinate-referenced objects (APs, walls, areas, survey routes) are shifted to match the cropped images.

---

## Capacity

Capacity reads the device mix out of a project you have already set up in
Ekahau and applies those ratios to another building. It exists so the thinking
you did once — how many devices a person carries, of which kinds, doing what —
does not have to be re-entered on every site.

**What it stores is ratios, not counts.** A project designed for 500 people
carrying 1,500 devices is stored as "three devices per person, split like so".
Applied to a 200-person building it writes 600. Headcount is the only number you
type.

### Capture a template

Open an `.esx` that is already set up the way you want. Capacity reads the
requirement areas and lists what it found: each device profile, each usage
profile, and the device count against it. Rows are shown exactly as authored —
two rows can name the same device and usage profile and still mean different
things, so they are never merged.

Type how many people that project was designed for, check the per-person column
matches what you intended, name the template and save it. Templates live in
`~/.wd_wireless_tools/capacity/`, outside the install folder, so an update never
touches them.

### Apply a template

Open the project you want to set up, pick a template, type the headcount, and
press **Apply and download**. Nothing is written to the file you opened — a new
copy is built and downloaded, so replacing the original stays your decision.

The preview says what will happen to each floor before you press anything:

| What it says | What it will do |
| --- | --- |
| **your area — adding N capacity items** | An area you drew is filled in. Your outline is not changed; only the devices are written into it |
| **create an area from the walls you drew** | No area on that floor, so one is created from the extent of the walls (or the APs, or the page, in that order) |
| **skip — this area already has N capacity items** | Left alone. Those are numbers you set, and overwriting them is the one destructive case |

Tick **Replace requirement areas that already exist** to overwrite that last
case. Even then your outline is kept — no area is ever deleted, in any of the
three situations.

### Profiles

A template names device and usage profiles by name, because Ekahau gives every
project its own internal identifiers and a template's identifiers mean nothing
in another file. Names are matched exactly first, then on the stem before a
comma or a bracket — so a template saying `Normal SLA` finds `Normal SLA
(2 Mbps)`, which is the same profile under a different Ekahau release.

Where a name genuinely could mean two profiles it stops and names both rather
than guessing. Ekahau ships both `Conferencing, GoToMeeting` and `Conferencing,
Lync/Skype`, so a template row saying only `Conferencing` is ambiguous and is
reported as such.

A template captured from a project carries the profile definitions with it, so
it can create a profile the target project does not have. The example template
shipped with the suite names only Ekahau stock profiles, so it applies to a new
project without creating anything.

---

## Prep

Prep does the setup work on a freshly imported project in one pass over the file, instead of three trips through three tools. Drop the `.esx` on it, choose which of the three things to do, check what it says it will do, and download the prepared copy.

- **Trim the canvas** — crops the empty paper off each CAD sheet and moves every AP, wall and area with it. The same work PlanTrim does.
- **Put a requirement area on every floor** — from a capacity template and a headcount, using the templates saved in WD Capacity.
- **Load the wall types** — adds the types from a Quick Walls template so they are there to draw with.

Each step is optional, each is previewed per floor before anything is written, and your project file is never written to.

The button is **Prepare and download**, under the preview. It is unavailable
until there is something to do, and the line beside it says which of the two
reasons applies — *"Pick at least one thing to do."* with nothing ticked, or
*"This project is already prepared — there is nothing left to do."* when every
step reports nothing to change. In that second case the preview still lists each
floor and why it was skipped, so a project that needs no work reads as finished
rather than as broken.

### Two ways to open a project, and they are not the same

**Drop it, or click to browse,** and the file is uploaded to the local server for the preview and again for the run. The prepared copy comes back as a download.

**Open from disk…** uses a file dialog instead, and Prep then reads the project where it already sits — nothing is uploaded at all. On a project of a couple of hundred megabytes that is the difference between a preview that keeps up with you and one that does not. The prepared copy is written **beside the original**, named `<name> (prepared).esx`, and Prep offers to show you the folder — because the next thing you do is open it in Ekahau.

Either way your original is never written to. The prepared copy is a new file, so keeping or discarding it stays your decision.

> **If the file dialog cannot open, Prep says so and gives you the browser's
> own picker instead.** The button reads *Opening…* while the dialog is up — it
> is allowed three minutes — and if it never appears you get a message naming
> the reason and the ordinary browse dialog, so the click still gets you in.
> Cancelling the dialog does nothing, which is the intended answer. Quick Walls
> behaves the same way. Before v2.100.9 a dialog that failed to open was
> reported as a cancel, so the button did nothing at all and said nothing.

> **Preparing again asks before replacing a prepared file that is already there.** A second run re-derives everything from the original, which is untouched and so still has all the work to do — so it would write that file again. By then it may be the file you opened in Ekahau and have been drawing in for an hour. Nothing inside the archive distinguishes *output Prep made* from *output you have since worked in*, so you are asked rather than assumed at.

Prep only knows where a project came from when you opened it through the dialog: a dropped file gives the browser no folder to report.

### The steps always run in the same order

Trim, then requirement areas, then wall types — whichever ones you pick, and whatever order you tick them in.

This is not a preference. A requirement area counts as something that has to stay on the plan, so an area put in before the trim holds the crop open. On a plan with no walls drawn yet the area covers the whole sheet, so it holds the crop open to the full sheet — and the trim then reports that there was nothing to crop. Nothing errors, the file opens, every floor is there, and the plan is simply the size it always was. The order is enforced in the code so this cannot happen.

### Running it again

Prep is meant to be run more than once. Run it on the fresh import, draw your walls in Ekahau, and run it again.

- Wall types already in the project are left alone. Replacing one would change the attenuation of every wall already drawn with it.
- A floor that has already been trimmed is skipped.
- A floor that already has a requirement area is left alone.

The exception is the whole reason to run it a second time. The first pass has no walls to measure, so the requirement area covers the entire plan. Once you have drawn walls, running Prep again tightens the area to them.

> **Only an area that still covers exactly the whole plan is replaced.** If you moved a corner, redrew it, or cut it around an atrium, it is your work and Prep never touches it. Untick **Re-measure areas that still cover the whole plan** to turn even that off.

### If a step cannot run

Prep refuses rather than guessing, and nothing is written when it does. The most common case is a capacity template that does not carry definitions for profiles the target project has never seen — it names each missing profile, and the fix is to re-capture the template from its source project, or add those profiles in Ekahau first.

---

## Suite Settings

**Menu → Suite Settings**, or `/settings`. Everything here follows *you* rather
than the document: it is saved once, on this machine, in
`~/.wd_wireless_tools/settings.json`, and is the same whichever browser you open
the suite in.

Two things are worth knowing before the list.

**A setting has exactly one home.** Some live on the Settings page, some on the
tool they belong to, some in a modal — but never in two places. That rule exists
because two of them once lived in two stores at the same time: the Settings page
showed a value that was not the one in force, and saving there did nothing at
all. Where a setting is edited somewhere other than the Settings page, the table
below says so.

**Panel widths, collapsed sections and dismissed tips are not here.** Those stay
in the browser deliberately — syncing a collapsed panel between machines would
be a regression, not a feature.

### Suite

| Setting | Where | What it does |
| --- | --- | --- |
| **Local project folder** | Settings | The folder the suite treats as home for your `.esx` files |
| **Backup copies to keep** | Settings | How many backups are kept per file before old ones are pruned. **0 turns backups off.** The page shows the total space used across all of them |

### Cloud Manager

| Setting | Where | What it does |
| --- | --- | --- |
| **Merge conflict rule** | Settings | What happens when a merge finds two files with the same name |
| **Live auto-refresh interval** | Settings | How often the listing re-reads the cloud while you watch it |
| **Default view (All / Mine / Others)** | Cloud Manager | Which owner filter the list *opens* on. Ships as **All**. The toolbar toggle changes only the current visit and never writes here — a per-browser copy of this is how two machines once disagreed about how many sites existed |

### Quick Walls

| Setting | Where | What it does |
| --- | --- | --- |
| **Units (inches / metres)** | Quick Walls | Thickness is entered in inches or metres. Heights are always in feet when this is imperial |
| **Default wall template** | Quick Walls | Which template the **Apply** button offers first |
| **Auto-apply the default template on open** | Quick Walls | Applies that template as soon as a project is opened, without asking |
| **Open the source folder after saving** | Settings | Reveals the folder in Explorer or Finder once a save finishes |

### Report

| Setting | Where | What it does |
| --- | --- | --- |
| **Client / company**, **Prepared by**, **Project reference**, **Revision** | Report settings | Printed on the cover and in the footer. Shared across every report template rather than saved per template |
| **Include revision in file name** | Report settings | Whether the saved PDF is named `Report - Type - v2.0 - Site` or `Report - Type - Site` |
| **Units (feet / metres)** | Report | How lengths are written. The `.esx` always stores metres; this changes only the report |
| **Section size on large floors** | Report | How much ground one section sheet covers when a large floor is split. Follows you, not the document |

Everything else in a report's options panel is remembered **per report type**
when you press **Save these as my defaults** — see *Settings that stay set*.

### Squirrel

All on the Settings page, and all about how a folder is sorted:

| Setting | What it does |
| --- | --- |
| **Default subfolders**, **Subfolder names** | Which folders are created and what they are called |
| **Custom destinations** | Send a chosen file type somewhere of your own |
| **Image / Floor-plan / Report extensions** | Which file extensions count as which kind of thing |
| **Report keywords**, **JSON report keywords** | Words in a filename that mark it as a report |
| **Folders to skip** | Folders left untouched when organising |
| **New site folder template** | The shape of a newly created site folder |
| **Squirrel rename rules** | Held on the Rename page itself |

### AP Labeler

Its naming defaults, templates, colour sequence and floor-walking order are kept
with the tool rather than on the Settings page, because they are edited while
looking at the plan they apply to.

---

## Data, Privacy, and Security

- Quick Walls and Report parse `.esx` files locally in the browser with JSZip.
- AP Labeler, PlanTrim, Capacity and Prep parse `.esx` files locally on the desktop server.
- Scale performs its conversions locally.
- The application contains no telemetry.
- Squirrel and Cloud Manager access only folders you choose.
- Cloud Manager contacts Ekahau Cloud only for actions you initiate against your account and tenant.
- Saved Cloud-session data is encrypted, with the key stored in the operating-system credential vault.
- **Menu → Forget Cloud Login** removes the saved Cloud session and its key.

There is no server-side file-processing service anywhere in the suite. Files are opened, changed and saved on your own machine.

### Backups of your projects

Every tool that writes to an `.esx` takes a copy of the original first, beside
the file it is replacing. That is separate from the update backup described
below — this one is about your survey files.

In **Settings → General**, **Backup copies to keep** controls how many are
retained per file. Older ones are pruned automatically after a successful write,
so the folder does not fill up.

- Set it to **0** to turn backups off entirely.
- The page shows the **total space used** across every backup the suite has
  taken, so the cost is visible rather than discovered later.

Pruning never fails an operation: a project written correctly is never reported
as an error because tidying up afterwards did not work.

### Backing up your settings

Everything you have configured can be saved to one file and restored from it.

**Where:** **Settings → Backup & restore**. It is its own section, below Quick
Walls. Two buttons, and a line above them saying when you last took a copy —
*"Last exported 12 days ago"* — so you can tell at a glance whether the backup
is worth anything.

#### Export

**⇩ Export to a file…** writes `wd-wireless-tools-settings-<date>.json` to your
downloads folder. It is meant to be read: open it and your own values are in
there as plain JSON, with a schema version and the time it was taken.

| In the file | Note |
|---|---|
| Every setting on the Settings page | |
| Your **wall templates** | **This is where your Quick Walls keyboard shortcuts live** — the shortcut number is a field on each wall type, not a store of its own |
| Your capacity templates | |
| Squirrel's rename rules and folder settings | |
| PlanTrim's saved crop boxes | |
| Cloud Manager's match decisions | The pairs you linked, and the ones you marked "not a match" |
| Your report details and cover image | |

**Not in the file:** your saved Ekahau Cloud login, and the per-project state
recording where you got to in each file. A credential does not belong in a
backup, and that state is not a preference.

#### What a restore deliberately does not bring back

Panel widths, which sections you left folded, and tips you have dismissed stay
with the browser you set them in. They *are* written into the file, so you can
open it and see everything — but importing skips them, and says how many it
skipped.

That is on purpose. Those values describe a window, not a person: carrying the
work machine's sidebar width onto the laptop would be a nuisance rather than a
rescue. Two exceptions do come back, because they follow you rather than the
window — **dark/light** and your **Ekahau sharing group**.

#### Import

**⇧ Import from a file…** restores one, and shows you what would change before
it writes anything:

- a line per value, with the old beside the new;
- anything already identical is counted rather than listed;
- **a folder path from another machine is called out by name** and checked
  against this disk, because your home project folder is not where the work
  machine keeps them;
- an export from a newer version is read as far as it can be, and anything
  unrecognised is listed rather than dropped.

**Import these changes** stays greyed out when the file would change nothing.

Before it writes, your current settings are copied aside as
`settings.backup-<date>.json`, next to `settings.json` in
`~/.wd_wireless_tools/`.

#### The two things this is for

1. **Getting back what you had.** If something overwrites your settings, the
   file puts them back — including the wall templates your keyboard shortcuts
   and wall colours live in.
2. **Moving between machines.** Export on the one at home, import on the one at
   work. Skip the project-folder path when it warns you; everything else
   travels.

#### Automatic copies

Two moments write a copy without being asked, because both can lose settings:

| When | Where |
|---|---|
| Before an **update** | `~/.wd_wireless_tools/settings-backups/` |
| Before an **import** | beside `settings.json`, as `settings.backup-<date>.json` |

How many are kept follows **Backup copies to keep** in Settings → General, and
the same **Check usage** and **Clean up** buttons find and prune them.

Setting that to **Off** stops the automatic ones — with one exception: the copy
taken immediately before an import is always kept, because it is the undo for
something you just asked for rather than a copy quietly piling up.

An automatic copy does not reset the "Last exported" line. That line is about
backups *you* took, and a file the suite wrote to protect itself is not one you
know about.

---

## Update or Uninstall

### Update

Open **Menu → About**. If a newer release exists, the panel shows the version you are on, the version available, and an **Update now** button.

1. Click **Update now**. Progress appears in the panel and in the launcher terminal window.
2. When it finishes, the panel reports the change—for example `Updated v2.5.0 → v2.6.0`.
3. Click **Restart to finish**. The suite restarts in a fresh terminal window and reloads on the new version.

The suite chooses the mechanism for you based on how it was installed:

| Install | What happens |
| --- | --- |
| Cloned with git | Fetches and checks out the newest release tag. Fast, and the previous version stays available in git. |
| Installed from a ZIP | Downloads the release asset, verifies its SHA-256, copies the current folder to a dated `.previous-vX.X.X` backup, then installs. |
| A development checkout | A **Pull now** button that fast-forwards your branch, plus the exact `git` command to run by hand. |

#### If you are running from a development checkout

A clone that also carries `tests/`, `scripts/`, `.github/` and `CLAUDE.md` is a
working copy, not an installation. Updating it the normal way would check out a
release tag over whatever you have in progress and leave the repository on a
detached HEAD, so **that** update is blocked on purpose.

**Press "Pull now".** It runs `git pull --ff-only` — it moves the branch you
are on forward and will not merge, check anything out, or rebase. When it is
done, **Restart to finish** loads the new code.

It refuses, and changes nothing, in four cases:

| What it finds | What it says |
|---|---|
| Uncommitted changes to tracked files | Names them, up to five — commit or stash them first |
| A detached HEAD | There is no branch to move; check one out |
| Commits of yours that aren't on GitHub | How many, that your work is safe, and to push or rebase from a terminal |
| No `.git` folder | There is nothing to pull |

A pull that brings commits without a version bump reports **"Pulled 3 commits —
still on v2.99.8"**. That is normal: the version number only moves when a
release bumps it.

Under **Or run it yourself**, About also prints the command with your own
install folder already in it, and a **Copy** button beside it:

```
git -C "<your install folder>" pull
```

Or simply `git pull` if you are already in that folder. Everything else in the
panel — the version you are on, the version available, the release notes —
works exactly as it does for any other install.

> This is the answer if the in-app updater has never seemed to do anything for
> you. Before **v2.99.7** this case said only "update it with git", which names
> a tool rather than a command, and there was no button at all until
> **v2.99.9**.

**Other ways to update** in the same panel covers the rest: switching a ZIP install over to git updates, copying the PowerShell command, or downloading the ZIP by hand. These open on their own if an update fails, along with a plain-language explanation of what went wrong.

#### If something goes wrong: the log file

**Menu → About → Diagnostics** shows the full path of the log file, with a
**Copy path** button next to it. The same path is printed in the black terminal
window when the suite starts, just under the address.

Everything that goes wrong is written there — including errors that only ever
appeared in the terminal window and used to vanish the moment it was closed.
Each entry is timestamped, and every launch writes a line saying which version
started, so a file you send answers "which build was this" on its own.

**It is kept across restarts, and the last seven days are retained.** Starting
the suite never wipes it, which matters because the natural reaction to an
error is to restart and see whether it happens again. Yesterday's entries are
filed under yesterday's date beside the live file.

**It cannot exceed 10 MB in total**, and in practice it is far smaller than
that: on a healthy install it grows by about **90 bytes per launch** and
nothing else — browsing every tool in the suite adds nothing at all. It only
grows when something actually goes wrong, which is the point of it.

If you hit something odd, that file is the thing to send. It stays on your own
computer: nothing is uploaded, and it is not part of any release.

#### Switching a ZIP install to git updates

If you installed from a ZIP, **Menu → About → Other ways to update → Switch to git updates** converts the folder in place. You do not need to reinstall or move anything.

The button shows exactly what will happen before you confirm:

- The folder becomes a tracked checkout of the repository.
- **You stay on the version you have now.** Converting and updating are separate steps, so switching never changes your code out from under you. Use **Update now** afterwards when you want the newer version.
- A dated backup of the folder is made first.
- Settings and templates are untouched — they live outside the folder.

Files you added yourself that aren't part of the app (a stray `.esx`, your own notes) are left alone.

On Windows, if git isn't installed the button reads **Switch to git updates (installs Git first)** and installs it with `winget` as part of the same step. If that can't work — no `winget` on older Windows 10 builds, no network, or a policy that blocks installs — the panel says so plainly and you stay on the ZIP method, which keeps working. On macOS the panel points you at `xcode-select --install` or `brew install git` rather than installing anything itself.

You can also update from a terminal, which is the right approach if the suite will not start:

```powershell
irm https://raw.githubusercontent.com/WeirDave/WD-Wireless-Tools/main/install.ps1 | iex
```

```bash
curl -fsSL https://raw.githubusercontent.com/WeirDave/WD-Wireless-Tools/main/install.sh | bash
```

#### What updating never touches

Wall templates, suite settings, Squirrel configuration, and your saved Cloud session live in `~/.wd_wireless_tools/`, outside the application folder. Updates replace only the application itself.

If you customized a wall template that ships with the suite, your edited copy is preserved automatically as a personal template the first time you update, and the panel tells you it did so. Personal templates always take precedence over the shipped ones; **Reset to built-in** in Quick Walls restores the shipped version.

### Uninstall

1. Use **Menu → Forget Cloud Login** if a session has been saved.
2. Stop the application by closing its terminal or pressing `Ctrl+C`.
3. Delete the extracted application folder.
4. For a completely clean removal, delete `~/.wd_wireless_tools/`.

## Troubleshooting

### Python is not recognized

Install Python 3.10 or newer. On Windows, enable **Add Python to PATH** during installation, then close and reopen the terminal.

### Windows SmartScreen blocks the launcher

Choose **More info → Run anyway** after confirming that you downloaded the asset from this repository's release page.

### macOS cannot verify the launcher

Right-click `Start WD Wireless Tools.command`, select **Open**, and confirm **Open**. This is normally needed only on first launch.

### Port 8675 is already in use

Another copy may already be running. Close it, or choose another port:

```bat
set PORT=8676 && "Start WD Wireless Tools.bat"
```

```bash
PORT=8676 bash "Start WD Wireless Tools.command"
```

### Cloud Manager cannot find a session

- Confirm you are signed into [Ekahau Cloud](https://cloud.ekahau.com/) in Chrome, Edge, or Firefox.
- Use a normal browser window, not Private or Incognito mode.
- Close and reopen the browser if its cookie database is locked.
- Return to Cloud Manager and retry the login check.

### The browser did not open

Open [http://localhost:8675](http://localhost:8675) manually while the launcher terminal remains open.

### A custom wall template is missing

Custom templates are saved under `~/.wd_wireless_tools/templates/`. If one has disappeared, check that folder — updating the suite never writes to it. Templates saved by an older browser-only build stayed in that browser's local storage and are not carried across.

## Getting Help

Use the guide built into the relevant tool first. For a reproducible bug or focused feature request, [open a GitHub issue](https://github.com/WeirDave/WD-Wireless-Tools/issues/new) and include:

- the suite and tool version;
- Windows or macOS version, and your browser and its version;
- the steps that reproduce the problem;
- the expected result; and
- the actual result or exact error text.

Do not attach client `.esx` files, credentials, Cloud-session data, or confidential screenshots to a public issue.

---

<div align="center">

**Built for wireless engineers, by a wireless engineer.**

[Return to the project home](../README.md)

</div>
