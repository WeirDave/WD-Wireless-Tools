# Vendored libraries

Third-party code copied into this folder, unmodified. Each file is the build the
package publishes, taken from the package's npm tarball. The tarball's own
integrity hash (the `sha512` the npm registry publishes for it) was checked
against the download before the file was used.

| Library | Version | File | SHA-256 of the file |
|---|---|---|---|
| JSZip | 3.10.2 | `jszip.min.js` | `7f839b2d4688b845c105ebf5d2f9803075f91ea0fe72bdaac176c3a04dd3d2c1` |
| mammoth | 1.13.0 | `mammoth.browser.min.js` | `92914a3708cfdf1e62cb553d1856a7fedab21da83d8ee82845de2f897b368cab` |
| pdf.js (`pdfjs-dist`) | 6.5.438 | `pdf.min.mjs` | `3a88402882cfa3e7e72c2c9b5149f52f0f88baf1c5b62aa11a41abdbc2072440` |
| pdf.js (`pdfjs-dist`) | 6.5.438 | `pdf.worker.min.mjs` | `1e64c8240e54735ec5913b37acd5134747799cb8c6bb3777c70adbc01232d2aa` |

`tests/test_vendored_libraries_match_the_manifest.py` hashes each file and fails
when it no longer matches this table, so replacing a library means updating this
file in the same change.

## What uses them

* JSZip reads and writes `.esx` archives in the browser (Quick Walls, Report,
  Scale and others).
* mammoth and pdf.js read `.docx` and `.pdf` text in Squirrel's Organizer
  (`web/assets/js/organizer.js`). pdf.js is opened with `isEvalSupported: false`.

## Updating one

1. `npm pack <package>@<version>` into an empty folder and check the printed
   integrity against `npm view <package>@<version> dist.integrity`.
2. Extract it into a separate folder. Copy only the file named above.
3. Run the text-extraction path of the new build against a small `.pdf` and
   `.docx` before adopting it.
4. Update the version and hash in the table.
