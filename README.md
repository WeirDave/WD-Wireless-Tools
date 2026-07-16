<p align="center">
  <img src="images/WD Wireless Tools - Transparent v6.0.png" alt="WD Wireless Tools" width="400">
</p>

<h3 align="center">A suite of Ekahau workflow tools</h3>

<p align="center">
  <a href="https://weirdave.github.io/WD-Wireless-Tools/"><img src="https://img.shields.io/badge/live%20demo-Quick%20Walls-5fa970?style=flat-square&logo=githubpages&logoColor=white" alt="Live Demo"></a>
  <a href="https://github.com/WeirDave/WD-Wireless-Tools/releases/latest"><img src="https://img.shields.io/github/v/release/WeirDave/WD-Wireless-Tools?style=flat-square&color=1e77ac" alt="Latest Release"></a>
  <img src="https://img.shields.io/badge/python-3.10%2B-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python 3.10+">
  <img src="https://img.shields.io/badge/platform-Windows%20%7C%20macOS-informational?style=flat-square" alt="Platform">
  <img src="https://img.shields.io/github/license/WeirDave/WD-Wireless-Tools?style=flat-square" alt="License">
</p>

> **Try Quick Walls live** → [weirdave.github.io/WD-Wireless-Tools/walls](https://weirdave.github.io/WD-Wireless-Tools/walls/) — no install, runs entirely in your browser.

---

## What is this?

**WD Wireless Tools** is a lightweight, browser-based toolkit for wireless engineers who use [Ekahau](https://www.ekahau.com/). It runs a tiny local Flask server and opens in your default browser — no installers, no Electron, no cloud dependency. **Quick Walls also runs live in a browser** at [weirdave.github.io/WD-Wireless-Tools/walls](https://weirdave.github.io/WD-Wireless-Tools/walls/) — no install at all.

The suite currently includes five tools:

<table>
<tr>
<td width="20%" align="center">
  <img src="images/WD Cloud Manager - Transparent v4.0.png" alt="Cloud Manager" width="150"><br>
  <b>Cloud Manager</b><br>
  <sub>v3.11</sub>
</td>
<td width="20%" align="center">
  <img src="images/WD Quick Walls v7.0.png" alt="Quick Walls" width="150"><br>
  <b>Quick Walls</b><br>
  <sub>v7.17</sub><br>
  <a href="https://weirdave.github.io/WD-Wireless-Tools/walls/"><sub>▶ Try live</sub></a>
</td>
<td width="20%" align="center">
  <img src="images/WD Squirrel - Transparent v13.png" alt="Squirrel" width="150"><br>
  <b>Squirrel</b><br>
  <sub>v1.8</sub>
</td>
<td width="20%" align="center">
  <div style="font-size:80px;line-height:1;">📏</div>
  <b>Scale</b><br>
  <sub>v1.1</sub><br>
  <a href="https://weirdave.github.io/WD-Wireless-Tools/scale/"><sub>▶ Try live</sub></a>
</td>
<td width="20%" align="center">
  <div style="font-size:80px;line-height:1;">📋</div>
  <b>Report</b><br>
  <sub>v1.0</sub><br>
  <a href="https://weirdave.github.io/WD-Wireless-Tools/report/"><sub>▶ Try live</sub></a>
</td>
</tr>
</table>

---

## The Tools

### Cloud Manager

Sync and manage your Ekahau Cloud sites and projects against your local `.esx` files. Browse your cloud inventory alongside your local folder, match files to sites, rename and delete in bulk, upload new projects, and move datasets between sites — all from one table view.

- Side-by-side cloud vs. local file view with character-level name diffs
- **Duplicates tab** — clusters near-duplicate files across cloud and local, marks newest and largest, one-click cleanup
- **≈ badge** on rows that belong to a duplicate cluster — click to jump to the tab
- Rename, delete, and reorganize projects and sites in bulk
- Upload `.esx` files directly to Ekahau Cloud
- Show in Explorer/Finder button on every local row
- Merge preview before combining projects
- Dark / light theme support

### Quick Walls

Open an `.esx` file, remap every wall type in your project using a fast, visual editor. Apply wall-type templates to standardize across projects, or save your own custom presets. **Available live in your browser** at [weirdave.github.io/WD-Wireless-Tools/walls](https://weirdave.github.io/WD-Wireless-Tools/walls/) — the hosted build uses `localStorage` for template persistence instead of the desktop template folder.

- Client-side `.esx` parsing (nothing leaves your machine)
- Visual wall-type grid with color-coded attenuation values
- Save / load wall-type templates (JSON)
- Auto-apply default templates on file open
- Keyboard shortcuts `[1]`–`[9]` mapped straight into the Ekahau wall picker
- Template store with "Recommended by WD" and Ekahau factory presets

### Squirrel

Your Ekahau file organizer. Point Squirrel at a folder and it will scan for loose `.esx` files, show you what needs organizing, and sort them into clean project subfolders.

- Scan a directory tree for `.esx` files
- Create new project folders with proper naming
- Configurable folder structure and naming rules
- Drag-and-drop-style batch organization

### Scale

Feet-and-inches ↔ decimal ↔ meters converter for Ekahau scale calibration. Paste `536'4"` from a floor plan and the tool spits out `536.333'`, `6436"`, `163.475 m`, and `163475 mm` — copy any of them with one click. **Available live in your browser** at [weirdave.github.io/WD-Wireless-Tools/scale](https://weirdave.github.io/WD-Wireless-Tools/scale/).

- Bidirectional (type on either side, both update)
- Handles architectural fractions (`4' 6-1/2"`, `4' 6 1/2"`, `1/2"`)
- Accepts a bare number (interpreted as feet on the imperial side, meters on the metric)
- Copy-to-clipboard on every output
- Pure client-side — no backend, works offline

### Report

Drop an `.esx` and get an installer-ready handoff document. The first report — **Directional Antenna Installation** — pulls every AP's mount type, mounting height, azimuth (with compass bearing), tilt, and antenna model straight out of the project, and lays out a floor-plan overview with a marker + direction arrow on each AP. Print → Save as PDF, hand to the installer. **Available live in your browser** at [weirdave.github.io/WD-Wireless-Tools/report](https://weirdave.github.io/WD-Wireless-Tools/report/).

- Parses `.esx` in the browser (JSZip) — nothing leaves your machine
- Floor plan overview with SVG marker + directional arrow per AP
- AP table with vendor, model, mount, height, azimuth, tilt, antenna
- Metric with imperial alongside, compass abbreviations, antenna spec legend — all togglable
- Print-optimized CSS: page-breaks per floor, backgrounds forced white, sidebar hidden

---

## Quick Start

### Just want to try Quick Walls?

Open [weirdave.github.io/WD-Wireless-Tools/walls](https://weirdave.github.io/WD-Wireless-Tools/walls/) — no install, no login, no Python. Drop an `.esx` file, edit walls, save the result. Your file never leaves your machine (JSZip parses it locally in the browser).

### Full suite — desktop install

The full suite (Cloud Manager + Quick Walls + Squirrel) needs Python because Cloud Manager and Squirrel access your file system and Ekahau Cloud session.

**Prerequisites:**

- **Python 3.10+** — [python.org/downloads](https://www.python.org/downloads/)
- A modern web browser (Chrome, Edge, Firefox, Safari)

**Run it:**

**Windows** — double-click `run.bat`

**macOS** — double-click `run.command` (or from Terminal):
```bash
bash run.command
```

**Manual**:
```bash
pip install -r requirements.txt
python server.py
```

The server starts on `http://localhost:8765` and opens your browser automatically.

---

## Project Structure

```
WD Wireless Tools/
├── server.py                 # Flask server — routes + API dispatch
├── run.bat                   # Windows launcher
├── run.command               # macOS launcher
├── requirements.txt          # Python dependencies
│
├── tools/
│   ├── cloud_manager.py      # Ekahau Cloud API integration + duplicates detection
│   ├── template_store.py     # Wall-type template persistence
│   └── folder_organizer.py   # Squirrel file scanning + sorting
│
├── web/                      # Desktop app source (single source of truth)
│   ├── home.html             # Suite landing page (desktop)
│   ├── cloud.html            # Cloud Manager UI
│   ├── walls.html            # Quick Walls UI (also served on GitHub Pages)
│   ├── organizer.html        # Squirrel UI
│   ├── guide*.html           # Built-in help pages
│   ├── pages/                # Hosted-only page templates (used by pages.yml)
│   │   ├── hosted-index.html         # Public landing page
│   │   ├── hosted-cloud-stub.html    # "Desktop only" page for /cloud/
│   │   └── hosted-organizer-stub.html # "Desktop only" page for /organizer/
│   └── assets/
│       ├── wd-tools.css      # Shared stylesheet
│       └── js/
│           ├── wd-shared.js  # Shared utilities (theme, toast, modal, escape)
│           ├── cloud.js      # Cloud Manager page logic
│           ├── walls.js      # Quick Walls page logic (with HOSTED runtime flag)
│           └── organizer.js  # Squirrel page logic
│
├── templates/                # Wall-type template presets (JSON) — bundled into hosted build
├── images/                   # Logos and branding assets
│
├── docs/
│   └── releases/             # Hand-authored release notes (published to GitHub Releases)
│
└── .github/workflows/
    ├── release.yml           # On tag push: zip source + publish GitHub Release
    └── pages.yml             # On push to main: build + deploy hosted site to GitHub Pages
```

---

## Dependencies

| Package | Purpose |
|---------|---------|
| [Flask](https://flask.palletsprojects.com/) | Local web server and API routing |
| [Requests](https://docs.python-requests.org/) | Ekahau Cloud API calls |
| [browser-cookie3](https://github.com/borisbabic/browser_cookie3) | Session auth for Ekahau Cloud |

All `.esx` file handling is done **client-side with JSZip** — your survey files never leave your machine.

---

## Contributing

This is a personal toolset, but if you're a wireless engineer with ideas or bugs, open an issue or a PR. Keep it simple.

---

## License

See [LICENSE](LICENSE) for details.

---

<p align="center">
  <sub>Built for wireless engineers, by a wireless engineer.</sub><br>
  <sub>Made with signal strength and caffeine by <a href="https://github.com/WeirDave">WeirDave</a></sub>
</p>
