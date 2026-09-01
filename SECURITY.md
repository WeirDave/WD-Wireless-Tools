# Security Policy

## Reporting a vulnerability

If you find a security vulnerability in WD Wireless Tools, **please report it privately** — do not open a public issue, since a public issue tips off potential attackers before a fix is out.

Use GitHub's **private vulnerability reporting**: go to the
[Security tab](https://github.com/WeirDave/WD-Wireless-Tools/security)
and click **Report a vulnerability**. This opens a private channel visible only to the maintainer.

Please include:

- What the vulnerability is and where it lives (file / feature / version).
- Steps to reproduce, or a minimal proof of concept.
- The suite version shown in the app footer (e.g. `v2.2.0`).

You'll get an acknowledgment as soon as it's seen. Confirmed issues are patched on a priority basis and credited in the release notes unless you ask otherwise.

## Supported versions

Only the **latest released version** is supported for security fixes. The current version is in `web/assets/versions.json` (`suite` key) and on GitHub Releases. If you're running an older build, update before reporting.

## Scope and design notes

WD Wireless Tools is a **local-first desktop application** — a Python server running on `localhost` that serves browser-based tool pages:

- There is no WD Wireless Tools account or telemetry backend. Your Ekahau project files, cloud session credentials, and settings all stay on your machine.
- Cloud Manager communicates directly with `cloud.ekahau.com` using the session cookie from your existing browser login. The session is encrypted at rest using the operating system credential vault.
- Quick Walls, Report, and Scale parse Ekahau `.esx` files entirely in the browser — no project data leaves the machine.
- The server binds to `localhost` only and rejects requests from non-loopback origins. Cross-origin POST requests are blocked before any action runs.
- Because the server runs locally, the most serious class of vulnerability is **anything that could allow a remote site to trigger server-side actions** (CSRF, DNS rebinding) or **inject script into tool pages** (XSS via crafted project data). Reports of these vectors are especially valued.
