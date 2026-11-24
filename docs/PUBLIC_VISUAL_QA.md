# Public visual QA (synthetic transport proof)

Scope: independently authored public fixtures only. No private repository checkout, private URLs, account data, secrets, real product source/bundle, or investment decision authority. This is a QA infrastructure probe, not a new evidence worker or private admission gate. Existing accepted Engine snapshot unchanged.

- Browser: pinned Playwright Chromium, 1200×760 and 390×844, click and layout assertions, no network requests from fixture.
- Native Windows: launch a real WinForms window on hosted runner, exercise interaction, require foreground/visible/on-screen window and verify known screen pixels, capture client area via CopyFromScreen. If interactive desktop unavailable, fail explicitly; never substitute DrawToBitmap or a browser screenshot for native-screen proof.
- Return PNGs in bounded, named, numbered base64 log records with full commit/run identity, byte length, pixel dimensions and SHA256. No upload-artifact step and no screenshot files committed. Only synthetic frames may use this transport.
- Receiver must independently decode, hash and view each image. A successful runner or an emitted digest is not sufficient by itself.
- This tests the capture/transport infrastructure, **not the private investment workstation**. Full product rendering requires a separately authorized public-safe source/bundle or a private/local runner. Do not let public CI access private code or credentials. Keep private final acceptance unchanged.

Status: IMPLEMENTED_NOT_RUNTIME_VALIDATED until actual run and observed-byte visual inspection.
