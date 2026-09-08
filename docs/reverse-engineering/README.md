# How the Ekahau Cloud endpoints were found

`tools/cloud_manager.py` talks to an API Ekahau does not document. These three
browser-console scripts are how that API was worked out: you paste one into the
devtools console on `cloud.ekahau.com`, drive the Ekahau web UI by hand, and it
prints the requests the page actually made.

They are kept for the same reason `docs/wall-types.md` is kept. The endpoints
still work, so nothing here is needed today — but if Ekahau changes the cloud
API, the fastest way back to a working client is to re-run the capture rather
than to guess from a diff of what broke. That reasoning was nearly lost once
already: this folder did not survive the clean repository at v2.0.0 and was
recovered from a backup.

## The scripts

| Script | What it captures |
|---|---|
| `capture_project_fields.js` | One-shot `GET /projectapi/v1/projects`, then prints the first project's full JSON and its field names. Use it to see what a project record actually contains. |
| `capture_upload.js` | Wraps `fetch` and `XMLHttpRequest` and records every POST/PUT while you upload a project through the Ekahau UI — method, URL, headers, and a body preview (including `FormData` field names). |
| `capture_download.js` | The same idea for the download path, plus a `PerformanceObserver` so it also catches resource loads the wrappers miss — S3 presigned URLs in particular. Filters to `/esxfileapi/`, `/projectapi/`, `amazonaws.com` and anything that looks like a download. |

## Using them

1. Sign in to the Ekahau cloud site and open devtools.
2. Paste the whole script into the console and press Enter. It starts listening
   immediately and prints a "Ready" line.
3. Perform the action in the Ekahau UI — upload a project, download one, etc.
4. Run `wdDump()` to print the whole trace and copy it to the clipboard.
   (`capture_project_fields.js` needs no dump step; it prints on load.)

Each capture wraps the page's own `fetch`/`XHR`, so a reload undoes it — paste
again for a fresh run.

## Before you paste a trace anywhere

**The traces contain live credentials.** Both capture scripts copy request
headers verbatim, which on an authenticated session includes the `Authorization`
bearer token, and `capture_download.js` records presigned S3 URLs whose query
string *is* the credential. A dumped trace is enough for someone else to act as
you until those expire.

Nothing is baked into these files — they are inert until run against a session
you are signed in to — but treat their output as a secret. Strip `Authorization`
headers and presigned query strings before pasting a trace into an issue, a
commit, or a chat window.
