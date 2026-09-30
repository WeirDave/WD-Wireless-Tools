# Ekahau Cloud API - what is known

Moved out of `CLAUDE.md` on 2026-09-30. It is reference material for Cloud
Manager work rather than a standing rule. `CLAUDE.md` keeps the summary.

## Uploading to Ekahau Cloud — what is known, and what is not

**Cloud Manager uploads over an existing cloud project, and has since
v2.104.6.** `replace_cloud_project` in `tools/cloud_manager.py` does it, the
row offers it as *"Local newer · replace cloud"*, and the whole-account planner
includes it. **This section opened by saying the opposite until 2026-09-19** —
it still described the Sync confirm as reading "that direction is not built
yet", a sentence that is in no file in the repository, and the backlog carried
a matching item from v2.104.6 to v2.145.0. Anybody picking it up would have begun
by building something that already worked.

**It is a composition, not an in-place write, and that is now settled rather
than pending.** The open question below — whether `batch/update` accepts
documents other than `project` — stopped mattering: `batch/update` is JSON, and
a project's floor plans are binary images fetched from S3 by id during
download. **A JSON document write cannot carry a re-cropped plan**, which is
exactly what his edits change. So in-place replacement is ruled out by what the
data is, not by an untested endpoint, and the capture route at the end of this
section would not change that. Don't re-open it on the strength of
`projectHistorys` being present.

**What the composition does, in order, and why the order is inverted from the
way he asked for it** (*"why can't we just automatically delete that first and
then upload the new one?"*): upload, verify the new project is really there and
really his file, **then** delete the old. Deleting first means a failed upload
leaves nothing in the cloud — his local copy survives but the shared copy other
people work from is gone, and he may not hear about it until somebody asks.
Uploading first means a failure leaves a duplicate: visible, annoying, and
removable in one click. Same result, safer way round. It also re-reads which
side is newer server-side before uploading (v2.142.0), carries the original
`siteId` over, and **names everyone who loses access** — a share is keyed to
the project id, so a new project does not carry it, and re-sharing other
people's projects on their behalf is not a side effect an upload should have.

**What is established about the API, kept because it is still the only written
record of it:**

- `GET /projectapi/v1/projects/{id}/batch` returns every document keyed
  exactly as the `.esx` members. `download_project` writes each key as
  `{key}.json` and the result is byte-identical to Ekahau's own download
  (`docs/releases/v1.8.41.md`).
- That batch response therefore **includes `projectHistorys`** — a real `.esx`
  contains `projectHistorys.json`, and it can only have come from there. So
  **the cloud stores the revision chain**, which is the data a server would
  need to detect a conflict. That is what makes in-place update with a
  sync-or-overwrite prompt plausible rather than wishful.
- `rename_project` already writes back in place:
  `PUT /projectapi/v1/projects/{id}/batch/update` with `{"project": {...}}`.
  Read-all and write-one, same shape.
- `upload_project` uses `esxfileapi/v1/projects/upload/initiate` → S3 PUT →
  `commit`. `initiate` takes only `fileName`/`fileExtension`, no project id,
  so that flow creates a **new** project. This is the web UI's upload path.
- `assign_to_site(site_id, dataset_id, type)` exists and works, so
  re-attaching a re-uploaded project to its original site is a call we
  already have.

**What is NOT established:** whether `batch/update` accepts documents other
than `project`. Nothing has been tested against it, and no speculative PUT
should be made against a real account to find out. *Moot for replacement, per
the note above — it could not carry the floor plans either way.*

**Dead ends — do not spend another session on these:**

- `docs/reverse-engineering/capture_upload.js` **cannot see the sync/overwrite
  prompt.** That dialog is in Ekahau AI Pro, the desktop client; the script
  wraps `fetch`/`XHR` in a browser page and desktop traffic never goes near
  it.
- **There is no public Ekahau Cloud API documentation.** That is why these
  capture scripts exist at all.
- Proxying the desktop client would settle it, but it means installing a
  trusted root certificate on a **work machine**. Not to be suggested.

**The cheap route that is still open.**
`docs/reverse-engineering/capture_project_fields.js` hits the project
*listing*, which is a browser operation and is unaffected by the desktop
problem. Field names alone answer whether a project record carries a
revision, version or etag. The safe one-liner, which prints no values and
copies nothing:

```js
fetch('/projectapi/v1/projects').then(r => r.json()).then(d => {
  const p = (Array.isArray(d) ? d : d.projects || d.items || [])[0] || {};
  console.log(Object.keys(p).sort().join(', '));
});
```

Whether the Ekahau Cloud **web** UI can replace an existing project is the
other open question. Note that if it only offers "upload new", capturing it
will reveal nothing about replacing — our `upload_project` already is that
flow.

**The fallback was taken, and it is the design.** Upload, verify, delete,
re-assign to the original site. The loss is narrower than earlier notes
claimed — `tags` live inside `project.json` and travel with the file, and
`projectHistorys.json` travels with it too. Shares are the one real loss, and
the decision there was made deliberately: `share_projects` exists and could
re-apply them, but re-sharing on his behalf is not a side effect an upload
should have, so the result **names the people who lost access** at the moment
it happens rather than when one of them asks why they cannot open it.

