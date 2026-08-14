# WD Wireless Tools User Manual

WD Wireless Tools is a local, browser-based suite for common Ekahau workflows. The desktop suite runs on Windows and macOS. Quick Walls, Scale, and Report can also run directly on the hosted site.

## Contents

1. [Install and launch](#install-and-launch)
2. [Home and navigation](#home-and-navigation)
3. [Cloud Manager](#cloud-manager)
4. [Quick Walls](#quick-walls)
5. [Squirrel](#squirrel)
6. [Scale](#scale)
7. [Report](#report)
8. [Data, privacy, and security](#data-privacy-and-security)
9. [Updating and uninstalling](#updating-and-uninstalling)
10. [Troubleshooting](#troubleshooting)

## Install and launch

### Requirements

- Windows or macOS.
- Python 3.10 or newer for the complete desktop suite.
- Chrome, Edge, or Firefox logged into Ekahau Cloud if you plan to use Cloud Manager.

### Installation

1. Open the latest GitHub release.
2. Under **Assets**, download `WD-Wireless-Tools-vX.X.X.zip`. Do not use GitHub's automatically generated “Source code” archives.
3. Extract the ZIP to a permanent folder.
4. On Windows, double-click `run.bat`. On macOS, double-click `run.command`.

The launcher installs missing Python packages on first run, starts a local server, and opens `http://localhost:8675` in your browser. Keep the terminal window open while using the suite.

If macOS blocks `run.command`, right-click it and select **Open**, then confirm **Open** once more.

### Manual launch

```bash
pip install -r requirements.txt
python server.py
```

## Home and navigation

The home page shows the five tools and their installed versions. Use a tool card to open it. Every tool also provides a menu for moving between tools, opening its guide, changing the theme, and viewing version information.

## Cloud Manager

Cloud Manager compares Ekahau Cloud projects with local `.esx` files and provides bulk project-management actions.

### First-time setup

1. Sign into Ekahau Cloud in a normal Chrome, Edge, or Firefox window.
2. Open Cloud Manager.
3. If prompted, use **Log in to Ekahau Cloud**, complete the login in the opened browser tab, and return to Cloud Manager.
4. Choose the local parent folder containing your Ekahau project folders.

### Main workflow

- Review cloud and local projects side by side.
- Use the row differences and match indicators to verify project pairs.
- Open the Duplicates view to review near-duplicate project files.
- Select rows before using bulk upload, download, rename, move, or delete actions.
- Read confirmation and preview screens carefully before any destructive operation.

Cloud Manager stores an encrypted copy of the active Cloud session locally. The encryption key is stored separately in Windows Credential Manager or macOS Keychain.

### Technical implementation note

Cloud Manager's `EkahauAPI` client in `tools/cloud_manager.py` includes reverse-engineered request flows needed for operations that the Ekahau web application performs from the browser, including the presigned upload sequence and client-side `.esx` download assembly. These calls are product code; local `.claude/` files are only development-tool configuration and are not required to run the suite.

Current branding source files are stored directly in `images/`. Superseded artwork and concept boards are retained under `images/legacy/` for project history and are excluded from downloadable release ZIPs.

## Quick Walls

Quick Walls edits wall types inside an Ekahau `.esx` project.

1. Drop an `.esx` file onto the page or click the drop area to browse.
2. Review the wall types detected in the project.
3. Choose replacement wall types individually or apply a saved template.
4. Save the updated `.esx` file.

Quick Walls supports reusable JSON wall templates and Ekahau factory presets. In the desktop suite, custom templates are stored in `templates/`. On the hosted site, templates are stored in browser local storage.

## Squirrel

Squirrel organizes loose Ekahau files into consistent project folders.

1. Choose the folder you want to scan.
2. Review the proposed classifications and destinations.
3. Adjust exclusions, naming rules, or destination folders where needed.
4. Confirm the operation only after the preview matches your intent.

Squirrel can create project folders, classify images, floor plans, and reports, rename files consistently, detect duplicates, and undo supported organization operations.

## Scale

Scale converts architectural measurements between feet-and-inches, decimal feet, inches, meters, and millimeters.

1. Enter a value on either the imperial or metric side.
2. Review the synchronized conversions.
3. Use the copy button beside the value you need.

Architectural fractions such as `4' 6-1/2"`, `4' 6 1/2"`, and `1/2"` are supported. A bare number is interpreted as feet on the imperial side and meters on the metric side.

## Report

Report turns an Ekahau `.esx` project into print-ready handoff documents.

1. Drop an `.esx` file onto the page or click the drop area to browse.
2. Choose one of the available report templates.
3. Configure the report sections, AP filters, label style, units, and other template-specific options.
4. Add a logo if desired.
5. Review the generated pages.
6. Print the report to PDF using your browser's print dialog.

### Available report templates

- Directional Antenna Installation / AP Placement
- Predictive Design / AP Placement
- Site Summary Sheet
- Interference / Rogue Devices
- Bill of Materials
- Antenna Aim Sheet
- Coverage Cell Boundary

The Change / Audit Report appears in the gallery as **Coming soon** and cannot yet be selected.

## Data, privacy, and security

- Quick Walls and Report parse `.esx` files locally in the browser with JSZip.
- The application includes no telemetry.
- Cloud Manager communicates with Ekahau Cloud only for actions you initiate against your own account and tenant.
- Cloud session data is encrypted locally; the key is kept in the operating system credential vault.
- Squirrel and Cloud Manager access only the local folders you select.
- Use **Menu → Forget Cloud Login** to remove the saved Cloud session and its credential-vault key.

## Updating and uninstalling

### Update

1. Download the newest version-numbered ZIP from GitHub Releases.
2. Extract it into a fresh folder.
3. Copy your custom `templates/` files into the new folder if you use desktop wall templates.

### Uninstall

1. Use **Menu → Forget Cloud Login** if Cloud Manager has saved a session.
2. Close the running terminal.
3. Delete the extracted tool folder.
4. For a completely clean removal, delete `~/.wd_wireless_tools/`.

## Troubleshooting

### Python is not recognized

Install Python 3.10 or newer. On Windows, enable **Add Python to PATH** during installation, then close and reopen your terminal.

### Port 8675 is already in use

Another copy may already be running. Close it, or launch on another port:

```bat
set PORT=8676 && run.bat
```

```bash
PORT=8676 bash run.command
```

### Cloud Manager cannot find a session

- Confirm that you are signed into `https://cloud.ekahau.com` in Chrome, Edge, or Firefox.
- Use a normal browser window, not Private or Incognito mode.
- Close and reopen the browser if its cookie database is locked.
- Safari, Brave, and Arc are not supported for session discovery.

### Browser does not open automatically

Open `http://localhost:8675` manually while the launcher terminal is still running.

### Getting more help

Use the built-in guide for the relevant tool. For reproducible bugs or feature requests, open an issue in the GitHub repository and include the tool version, operating system, expected behavior, and what happened instead. Do not attach client `.esx` files or credentials to a public issue.
