<div align="center">

<img src="../web/assets/wd-wireless-tools-v8.0-720x720.png" alt="WD Wireless Tools" width="150">

# WD Wireless Tools

## User Manual

**Practical guidance for the complete Ekahau workflow suite.**

![Local First](https://img.shields.io/badge/local--first-private-5fa970?style=flat-square)
![No Telemetry](https://img.shields.io/badge/telemetry-none-5fa970?style=flat-square)
![Platforms](https://img.shields.io/badge/platform-Windows%20%7C%20macOS-6b7280?style=flat-square)

[Home](../README.md) · [Browser Tools](https://weirdave.github.io/WD-Wireless-Tools/) · [Latest Release](https://github.com/WeirDave/WD-Wireless-Tools/releases/latest) · [Get Help](https://github.com/WeirDave/WD-Wireless-Tools/issues)

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
- [Data, Privacy, and Security](#data-privacy-and-security)
- [Update or Uninstall](#update-or-uninstall)
- [Troubleshooting](#troubleshooting)
- [Getting Help](#getting-help)

---

## Start Here

WD Wireless Tools is a local, browser-based suite for common Ekahau workflows. The complete desktop suite runs on Windows and macOS. Quick Walls, Scale, and Report can also run directly from the public website.

| If you need to… | Use | Available |
|---|---|---|
| Compare local projects with Ekahau Cloud | Cloud Manager | Desktop |
| Remap wall types or apply wall templates | Quick Walls | Desktop + Web |
| Organize loose project files | Squirrel | Desktop |
| Convert architectural measurements | Scale | Desktop + Web |
| Generate installer-ready documents | Report | Desktop + Web |

> **Before working on production files:** retain a backup and review every preview before a bulk rename, move, delete, or Cloud operation.

## Install and Launch

### Requirements

- Windows or macOS
- Python 3.10 or newer for the complete desktop suite
- Chrome, Edge, or Firefox signed into Ekahau Cloud for Cloud Manager

You do not need Python to use the [hosted browser tools](https://weirdave.github.io/WD-Wireless-Tools/).

### Install the desktop suite

1. Open the [latest GitHub release](https://github.com/WeirDave/WD-Wireless-Tools/releases/latest).
2. Under **Assets**, download `WD-Wireless-Tools-vX.X.X.zip`. Do not choose GitHub's automatically generated “Source code” archives.
3. Extract the ZIP to a permanent folder.
4. On Windows, double-click `WD Wireless Tools Start.bat`. On macOS, double-click `WD Wireless Tools Start.command`.

The launcher installs any missing Python packages on first run, starts the local service, and opens [http://localhost:8675](http://localhost:8675). Keep the terminal window open while using the suite.

> **macOS first launch:** if Gatekeeper blocks `WD Wireless Tools Start.command`, right-click the file, choose **Open**, and confirm **Open** once more.

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

### Perform an operation

1. Filter or search until the intended projects are visible.
2. Select the relevant rows.
3. Choose the upload, download, rename, move, merge, or delete action.
4. Read the preview and confirm the exact source, destination, and number of affected items.
5. Start the operation and review its completion status.

Use **Show in Explorer/Finder** to verify a local file directly before acting on it.

> **Cloud actions are real actions.** A clean preview is your last checkpoint before a rename, move, overwrite, or deletion reaches the selected files or tenant.

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

### Use templates

- Apply an included Ekahau or WD template to create a mapping quickly.
- Save a custom mapping as a reusable JSON template.
- Configure a default template when you want it proposed automatically on file open.
- Use number keys `1` through `9` when working with the corresponding wall-picker positions.

Desktop custom templates live in `templates/`. The hosted build stores custom templates in that browser's local storage, so templates do not automatically move between browsers or computers.

Open [Quick Walls on the web](https://weirdave.github.io/WD-Wireless-Tools/walls/).

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

> Start with a small representative folder if you are introducing new naming rules. Once the preview is right, apply the same rules to the larger collection.

---

## Scale

Scale converts architectural measurements between feet-and-inches, decimal feet, inches, meters, and millimeters.

1. Enter a value on either the imperial or metric side.
2. Review the synchronized conversions.
3. Select the copy control beside the value you need.

Supported architectural formats include `4' 6-1/2"`, `4' 6 1/2"`, and `1/2"`. A bare number is treated as feet on the imperial side and meters on the metric side.

Open [Scale on the web](https://weirdave.github.io/WD-Wireless-Tools/scale/).

---

## Report

Report turns an Ekahau `.esx` project into print-ready handoff documentation.

### Build a report

1. Drop an `.esx` file onto the page, or select the drop area to browse.
2. Choose an available report template.
3. Configure sections, AP filters, label style, units, and template-specific options.
4. Add a logo when the document requires customer or company branding.
5. Review every generated page.
6. Use the browser print dialog to print or save the result as PDF.

### Available report templates

- Directional Antenna Installation / AP Placement
- Predictive Design / AP Placement
- Site Summary Sheet
- Interference / Rogue Devices
- Bill of Materials
- Antenna Aim Sheet
- Coverage Cell Boundary

The Change / Audit Report appears as **Coming soon** and cannot yet be selected.

### AP labels

Floor-plan markers and AP-table labels come from the AP names inside the project. When a name ends in an AP designator such as `SITE-B1-01-AP42`, the short-label option can show `42` for quick map-to-table cross-reference. Turn off **Short number labels on the plan** when full names are preferable.

### Print cleanly

- Confirm the expected paper size and orientation in the browser print dialog.
- Enable background graphics if your browser offers that option.
- Inspect page breaks, map readability, and table wrapping in the preview.
- Save to PDF and inspect the final PDF before sending it to installers or customers.

Open [Report on the web](https://weirdave.github.io/WD-Wireless-Tools/report/).

---

## Data, Privacy, and Security

- Quick Walls and Report parse `.esx` files locally in the browser with JSZip.
- Scale performs its conversions locally.
- The application contains no telemetry.
- Squirrel and Cloud Manager access only folders you choose.
- Cloud Manager contacts Ekahau Cloud only for actions you initiate against your account and tenant.
- Saved Cloud-session data is encrypted, with the key stored in the operating-system credential vault.
- **Menu → Forget Cloud Login** removes the saved Cloud session and its key.

The hosted site has no server-side file-processing service. Files opened by the hosted tools remain in your browser.

## Update or Uninstall

### Update

1. Download the newest versioned ZIP from [GitHub Releases](https://github.com/WeirDave/WD-Wireless-Tools/releases/latest).
2. Extract it into a fresh folder.
3. Copy custom files from `templates/` into the new folder if you use desktop wall templates.
4. Start the new version and confirm the version shown on the home page.

Keeping the old extracted folder until the new version passes your normal workflow provides a simple rollback.

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

Right-click `WD Wireless Tools Start.command`, select **Open**, and confirm **Open**. This is normally needed only on first launch.

### Port 8675 is already in use

Another copy may already be running. Close it, or choose another port:

```bat
set PORT=8676 && "WD Wireless Tools Start.bat"
```

```bash
PORT=8676 bash "WD Wireless Tools Start.command"
```

### Cloud Manager cannot find a session

- Confirm you are signed into [Ekahau Cloud](https://cloud.ekahau.com/) in Chrome, Edge, or Firefox.
- Use a normal browser window, not Private or Incognito mode.
- Close and reopen the browser if its cookie database is locked.
- Return to Cloud Manager and retry the login check.

### The browser did not open

Open [http://localhost:8675](http://localhost:8675) manually while the launcher terminal remains open.

### A hosted wall template is missing

Hosted templates are saved in browser local storage. Use the same browser and browser profile, or export/import the JSON template.

## Getting Help

Use the guide built into the relevant tool first. For a reproducible bug or focused feature request, [open a GitHub issue](https://github.com/WeirDave/WD-Wireless-Tools/issues/new) and include:

- the suite and tool version;
- Windows or macOS version, or browser/version for a hosted tool;
- the steps that reproduce the problem;
- the expected result; and
- the actual result or exact error text.

Do not attach client `.esx` files, credentials, Cloud-session data, or confidential screenshots to a public issue.

---

<div align="center">

**Built for wireless engineers, by a wireless engineer.**

[Return to the project home](../README.md)

</div>
