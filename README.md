<div align="center">

<img src="web/assets/wd-wireless-tools-v8.0-720x720.png" alt="WD Wireless Tools" width="170">

# WD Wireless Tools

**A suite of Ekahau workflow tools.**

Five focused utilities for organizing projects, managing Ekahau Cloud, editing walls,
converting scale, and building installer-ready reports.

[![Latest Release](https://img.shields.io/github/v/release/WeirDave/WD-Wireless-Tools?style=for-the-badge&color=1e77ac)](https://github.com/WeirDave/WD-Wireless-Tools/releases/latest)
[![Tests](https://img.shields.io/github/actions/workflow/status/WeirDave/WD-Wireless-Tools/tests.yml?branch=main&style=for-the-badge&label=Windows%20%2B%20macOS)](https://github.com/WeirDave/WD-Wireless-Tools/actions/workflows/tests.yml)
[![License](https://img.shields.io/github/license/WeirDave/WD-Wireless-Tools?style=for-the-badge)](LICENSE)

![Local First](https://img.shields.io/badge/local--first-private-5fa970?style=flat-square)
![No Telemetry](https://img.shields.io/badge/telemetry-none-5fa970?style=flat-square)
![Python](https://img.shields.io/badge/python-3.10%2B-3776ab?style=flat-square&logo=python&logoColor=white)
![Platforms](https://img.shields.io/badge/platform-Windows%20%7C%20macOS-6b7280?style=flat-square)

### [→ Launch the browser tools](https://weirdave.github.io/WD-Wireless-Tools/)

[Read the User Manual](docs/USER_MANUAL.md) · [Download the Full Suite](https://github.com/WeirDave/WD-Wireless-Tools/releases/latest) · [Report an Issue](https://github.com/WeirDave/WD-Wireless-Tools/issues)

</div>

<table>
<tr>
<td width="20%" align="center"><img src="web/assets/cloud-manager-v8.0-560x560.png" alt="Cloud Manager" width="105"><br><b>Cloud Manager</b><br><sub>v4.17.0 · Desktop</sub></td>
<td width="20%" align="center"><a href="https://weirdave.github.io/WD-Wireless-Tools/walls/"><img src="web/assets/quick-walls-v8.0-560x560.png" alt="Quick Walls" width="105"></a><br><b>Quick Walls</b><br><sub>v7.42 · Desktop + Web</sub></td>
<td width="20%" align="center"><img src="web/assets/squirrel-v8.0-560x560.png" alt="Squirrel" width="105"><br><b>Squirrel</b><br><sub>v1.26.0 · Desktop</sub></td>
<td width="20%" align="center"><a href="https://weirdave.github.io/WD-Wireless-Tools/scale/"><img src="web/assets/scale-v8.0-560x560.png" alt="Scale" width="105"></a><br><b>Scale</b><br><sub>v1.5 · Desktop + Web</sub></td>
<td width="20%" align="center"><a href="https://weirdave.github.io/WD-Wireless-Tools/report/"><img src="web/assets/report-v8.0-560x560.png" alt="Report" width="105"></a><br><b>Report</b><br><sub>v2.31.1 · Desktop + Web</sub></td>
</tr>
</table>

---

## Table of Contents

- [What WD Wireless Tools Does](#what-wd-wireless-tools-does)
- [Five Tools, One Workflow](#five-tools-one-workflow)
- [Quick Start](#quick-start)
- [Privacy and Local-First Design](#privacy-and-local-first-design)
- [First Run](#first-run)
- [Troubleshooting](#troubleshooting)
- [Project Structure](#project-structure)
- [Help and Support](#help-and-support)

---

## What WD Wireless Tools Does

WD Wireless Tools removes the repetitive work around an Ekahau project. It gives wireless engineers a fast local workspace for cloud and file organization, wall remapping, scale conversion, and field-ready reporting—without turning those jobs into another subscription or another place to upload client data.

The full suite runs from a tiny local Flask server and opens in your normal browser. Quick Walls, Scale, and Report are also available as hosted, client-side tools for jobs that do not need desktop file-system or Ekahau Cloud access.

> **The important distinction:** the interface is browser-based, but your working data stays local. The hosted tools process files in your browser; Cloud Manager contacts Ekahau Cloud only when you direct it to operate on your own tenant.

## Five Tools, One Workflow

### Cloud Manager

Compare Ekahau Cloud projects with local `.esx` files, find duplicates, and manage project movement from a single table view.

- Side-by-side cloud and local inventory with character-level name differences
- Duplicate clustering with newest/largest indicators and focused cleanup
- Bulk upload, download, rename, move, and delete operations with previews
- Direct access to local files in Explorer or Finder
- Encrypted local Cloud-session cache backed by the operating-system credential vault

Cloud Manager's `EkahauAPI` client implements the reverse-engineered upload/download flows required to reproduce the web application's presigned upload and client-side `.esx` assembly behavior.

### Quick Walls

Open an `.esx`, visually remap every wall type, apply reusable templates, and save the updated project.

- Local, client-side `.esx` parsing with JSZip
- Color-coded wall types and attenuation values
- Ekahau factory presets plus custom JSON templates
- Default-template auto-apply and `[1]`–`[9]` keyboard shortcuts
- [Runs directly in the browser](https://weirdave.github.io/WD-Wireless-Tools/walls/)

### Squirrel

Turn loose project files into a predictable folder structure after reviewing the proposed result.

- Recursive `.esx` discovery and project classification
- Configurable naming and folder rules
- Image, floor-plan, and report organization
- Duplicate detection and supported-operation undo

### Scale

Convert architectural measurements between feet-and-inches, decimal feet, inches, meters, and millimeters.

- Bidirectional conversion with synchronized results
- Architectural fractions such as `4' 6-1/2"`, `4' 6 1/2"`, and `1/2"`
- One-click copying for every output
- Pure client-side operation, including the [hosted version](https://weirdave.github.io/WD-Wireless-Tools/scale/)

### Report

Transform an `.esx` project into print-ready, installer-facing documents. Seven report formats are available today:

- **AP Installation**
- **Predictive Design / AP Placement**
- **Site Summary Sheet**
- **Interference / Rogue Devices**
- **Bill of Materials**
- **Antenna Aim Sheet**
- **Coverage Cell Boundary**

The **Change / Audit Report (coming soon)** is visible in the gallery but is not selectable yet. Every available report supports its own options and print-optimized renderer through the shared report registry. Try it in the [hosted Report tool](https://weirdave.github.io/WD-Wireless-Tools/report/).

---

## Quick Start

### Try the browser tools

Open the [hosted tool suite](https://weirdave.github.io/WD-Wireless-Tools/) to use Quick Walls, Scale, or Report immediately. There is no installation or login. Cloud Manager and Squirrel remain desktop-only because they need Ekahau Cloud or local file-system access.

### Install the complete desktop suite

Install [Python 3.10 or newer](https://www.python.org/downloads/) first. On Windows, enable **Add Python to PATH** during installation.

Then run one command. It installs the suite, or updates it if it is already there.

**Windows (PowerShell):**

```powershell
irm https://raw.githubusercontent.com/WeirDave/WD-Wireless-Tools/main/install.ps1 | iex
```

**macOS / Linux:**

```bash
curl -fsSL https://raw.githubusercontent.com/WeirDave/WD-Wireless-Tools/main/install.sh | bash
```

On a fresh install it asks which method you want:

| Method | What it means |
| --- | --- |
| **Git** | The folder is a tracked checkout. Updates take seconds because only what changed is downloaded. If git isn't installed, the installer offers to install it first with `winget` — usually under a minute. |
| **ZIP** | No dependencies. Each update re-downloads the whole app and verifies its SHA-256. |

Pick either — you can switch later from **Menu → About** without reinstalling. Skip the prompt with `-Method git` or `-Method zip` (`--method` on macOS/Linux). Either way the installer adds missing Python packages and offers to launch the suite.

<details>
<summary>Manual install from the ZIP</summary>

1. Open the [latest release](https://github.com/WeirDave/WD-Wireless-Tools/releases/latest) and download the versioned `WD-Wireless-Tools-vX.X.X.zip` asset—not GitHub's automatic “Source code” archive.
2. Extract the ZIP to a permanent folder.
3. Double-click `Start WD Wireless Tools.bat` on Windows or `Start WD Wireless Tools.command` on macOS.

</details>

The launcher installs missing dependencies, starts the local service, and opens `http://localhost:8675`. Keep its terminal window open while using the suite.

For detailed, task-by-task instructions, see the **[WD Wireless Tools User Manual](docs/USER_MANUAL.md)**.

### Updating

Open **Menu → About** and click **Update now**. The suite detects how it was installed and uses the right mechanism—a git pull for a cloned install, a verified ZIP download otherwise—then offers to restart into the new version. Progress is printed in the launcher terminal as it happens.

Wall templates, settings, and your saved Cloud session live in `~/.wd_wireless_tools/`, outside the application folder, so an update never touches them.

Re-running the install command above does the same thing from a terminal, which is useful on a machine where the suite will not start.

### Manual launch

```bash
pip install -r requirements.txt
python server.py
```

The startup banner identifies the installed suite version:

```text
WIRELESS TOOLS  v2.10.0
A suite of Ekahau workflow tools.

Local suite: http://localhost:8675/
Press CTRL+C in this window to stop WD Wireless Tools.
```

---

## Privacy and Local-First Design

- Quick Walls and Report parse `.esx` archives locally in your browser with JSZip.
- Scale performs every calculation in the browser.
- Squirrel accesses only the local folder you select.
- Cloud Manager connects only to the Ekahau Cloud account and local folder you select.
- Saved Cloud-session data is encrypted; its key lives separately in Windows Credential Manager or macOS Keychain.
- There is no telemetry.

No hosted WD Wireless Tools service receives your survey files. As with any production workflow, keep backups and review previews before bulk file or Cloud operations.

## First Run

### Cloud Manager

Sign into Ekahau Cloud in a normal Chrome, Edge, or Firefox window, then choose the parent folder containing your local Ekahau projects. Safari, Private, and Incognito sessions are not supported for session discovery. Your selections are remembered locally.

### Quick Walls, Scale, and Report

No setup is required. Drop an `.esx` into Quick Walls or Report, or type a measurement in Scale.

### Squirrel

Choose a folder containing loose project files. Squirrel shows the proposed organization before moving anything.

### Local data locations

- Custom desktop wall templates: `templates/`
- Cloud Manager settings: `~/.wd_wireless_tools/`
- Hosted Quick Walls templates: the browser's local storage

## Troubleshooting

### Python is not recognized

Install Python 3.10 or newer and enable **Add Python to PATH** on Windows. Reopen the terminal afterward.

### macOS blocks `Start WD Wireless Tools.command`

Right-click `Start WD Wireless Tools.command`, choose **Open**, then confirm **Open**. This is normally required only once.

### Cloud Manager cannot find a session

Confirm that you are signed into `https://cloud.ekahau.com` in a normal Chrome, Edge, or Firefox window. Close and reopen the browser if its cookie database is locked.

### Port 8675 is already in use

Close the other running instance, or choose another port:

```bat
set PORT=8676 && "Start WD Wireless Tools.bat"
```

```bash
PORT=8676 bash "Start WD Wireless Tools.command"
```

### Browser does not open automatically

Open [http://localhost:8675](http://localhost:8675) manually while the launcher terminal remains open.

## Project Structure

```text
WD-Wireless-Tools/
├── server.py                          # Local Flask/Waitress service and API routes
├── Start WD Wireless Tools.bat        # Windows launcher
├── Start WD Wireless Tools.command    # macOS launcher
├── requirements.txt                   # Python dependencies
├── BACKLOG.md                         # Unfinished product work only
├── tools/
│   ├── cloud_manager.py               # Cloud client and reverse-engineered upload/download flows
│   ├── template_store.py              # Wall-template persistence
│   ├── folder_organizer.py            # Squirrel scanning and organization
│   ├── rename_manager.py              # Bulk rename operations
│   └── settings.py                    # Suite-wide settings and migration
├── web/                               # Application source and hosted page templates
│   ├── assets/
│   │   ├── versions.json              # Suite and component versions
│   │   ├── lib/                       # Vendored browser libraries
│   │   └── js/
│   │       ├── wd-shared.js           # Shared UI utilities
│   │       ├── walls-swap.js          # Wall-remapping workflow
│   │       └── ...                    # Tool-specific application code
│   └── pages/                         # GitHub Pages landing/stub templates
├── templates/                         # Bundled wall-type templates
├── docs/
│   └── USER_MANUAL.md                 # Complete user documentation
├── scripts/
│   ├── build_release.py               # Allowlisted release ZIP builder
│   └── make_test_projects.py          # Fictional ESX fixture generator
├── tests/                             # Python, server, asset, and JavaScript safety tests
└── .github/workflows/                 # Tests, releases, and Pages deployment
```

The local `.claude/` directory is development-tool configuration, not application code. It is intentionally excluded because it may contain machine-specific paths and permissions.

## Help and Support

- Start with the [User Manual](docs/USER_MANUAL.md) or the guide built into each tool.
- Search existing [GitHub issues](https://github.com/WeirDave/WD-Wireless-Tools/issues).
- For a reproducible bug or focused feature request, [open an issue](https://github.com/WeirDave/WD-Wireless-Tools/issues/new) with the tool version, operating system, expected result, and actual result.
- Never attach client `.esx` files, credentials, session data, or other confidential material to a public issue.

Contributions are welcome when they keep the tools focused, understandable, and safe for real wireless work.

## License

Released under the [MIT License](LICENSE). © R David Paine III.

---

<div align="center">

**Built for wireless engineers, by a wireless engineer.**

Made with signal strength and caffeine by [WeirDave](https://github.com/WeirDave).

</div>
