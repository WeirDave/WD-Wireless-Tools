<p align="center">
  <img src="images/WD Wireless Tools - Transparent v6.0.png" alt="WD Wireless Tools" width="400">
</p>

<h3 align="center">A suite of Ekahau workflow tools</h3>

<p align="center">
  <a href="https://github.com/WeirDave/WD-Wireless-Tools/releases/latest"><img src="https://img.shields.io/github/v/release/WeirDave/WD-Wireless-Tools?style=flat-square&color=1e77ac" alt="Latest Release"></a>
  <img src="https://img.shields.io/badge/python-3.10%2B-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python 3.10+">
  <img src="https://img.shields.io/badge/platform-Windows%20%7C%20macOS-informational?style=flat-square" alt="Platform">
  <img src="https://img.shields.io/github/license/WeirDave/WD-Wireless-Tools?style=flat-square" alt="License">
</p>

---

## What is this?

**WD Wireless Tools** is a lightweight, browser-based toolkit for wireless engineers who use [Ekahau](https://www.ekahau.com/). It runs a tiny local Flask server and opens in your default browser — no installers, no Electron, no cloud dependency.

The suite currently includes three tools:

<table>
<tr>
<td width="33%" align="center">
  <img src="images/WD Cloud Manager - Transparent v4.0.png" alt="Cloud Manager" width="200"><br>
  <b>Cloud Manager</b><br>
  <sub>v3.6</sub>
</td>
<td width="33%" align="center">
  <img src="images/WD Quick Walls v7.0.png" alt="Quick Walls" width="200"><br>
  <b>Quick Walls</b><br>
  <sub>v7.15</sub>
</td>
<td width="33%" align="center">
  <img src="images/WD Squirrel - Transparent v13.png" alt="Squirrel" width="200"><br>
  <b>Squirrel</b><br>
  <sub>v1.7</sub>
</td>
</tr>
</table>

---

## The Tools

### Cloud Manager

Sync and manage your Ekahau Cloud sites and projects against your local `.esx` files. Browse your cloud inventory alongside your local folder, match files to sites, rename and delete in bulk, upload new projects, and move datasets between sites — all from one table view.

- Side-by-side cloud vs. local file view
- Rename, delete, and reorganize projects and sites
- Upload `.esx` files directly to Ekahau Cloud
- Merge preview before combining projects
- Dark / light theme support

### Quick Walls

Open an `.esx` file, remap every wall type in your project using a fast, visual editor. Apply wall-type templates to standardize across projects, or save your own custom presets.

- Client-side `.esx` parsing (nothing leaves your machine)
- Visual wall-type grid with color-coded attenuation values
- Save / load wall-type templates (JSON)
- Auto-apply default templates on file open
- Undo support and Ekahau-defaults reset
- Template store with "Recommended by WD" presets

### Squirrel

Your Ekahau file organizer. Point Squirrel at a folder and it will scan for loose `.esx` files, show you what needs organizing, and sort them into clean project subfolders.

- Scan a directory tree for `.esx` files
- Create new project folders with proper naming
- Configurable folder structure and naming rules
- Drag-and-drop-style batch organization

---

## Quick Start

### Prerequisites

- **Python 3.10+** — [python.org/downloads](https://www.python.org/downloads/)
- A modern web browser (Chrome, Edge, Firefox, Safari)

### Run it

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
│   ├── cloud_manager.py      # Ekahau Cloud API integration
│   ├── template_store.py     # Wall-type template persistence
│   └── folder_organizer.py   # Squirrel file scanning + sorting
│
├── web/
│   ├── home.html             # Suite landing page
│   ├── cloud.html            # Cloud Manager UI
│   ├── walls.html            # Quick Walls UI
│   ├── organizer.html        # Squirrel UI
│   ├── guide*.html           # Built-in help pages
│   └── assets/
│       ├── wd-tools.css      # Shared stylesheet
│       └── wd-nav.js         # Shared topbar + theme logic
│
├── templates/                # Wall-type template presets (JSON)
└── images/                   # Logos and branding assets
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
