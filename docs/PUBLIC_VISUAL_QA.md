# Public visual QA (synthetic transport proof)

Scope: independently authored public fixtures only. No private repository checkout, private URLs, account data, secrets, real product source/bundle, or investment decision authority. This is a QA infrastructure probe, not a new evidence worker or private admission gate. Existing accepted Engine snapshot unchanged.

- Browser: pinned Playwright Chromium, 1200×760 and 390×844, click and layout assertions, no network requests from fixture.
- Native Windows: launch a real WinForms window on hosted runner, exercise interaction, require foreground/visible/on-screen window and verify known screen pixels, capture client area via CopyFromScreen. If interactive desktop unavailable, fail explicitly; never substitute DrawToBitmap or a browser screenshot for native-screen proof.
- Return PNGs in bounded, named, numbered base64 log records with full commit/run identity, byte length, pixel dimensions and SHA256. No upload-artifact step and no screenshot files committed. Only synthetic frames may use this transport.
- Receiver must independently decode, hash and view each image. A successful runner or an emitted digest is not sufficient by itself.
- This tests the capture/transport infrastructure, **not the private investment workstation**. Full product rendering requires a separately authorized public-safe source/bundle or a private/local runner. Do not let public CI access private code or credentials. Keep private final acceptance unchanged.

Initial implementation status was IMPLEMENTED_NOT_RUNTIME_VALIDATED; see commit-bound observed evidence below.

## Observed public runtime evidence — 2026-11-24

- Initial native proof: run [45369501616](https://github.com/riyuewuxing/InvestmentEvidenceEngine/actions/runs/45369501616), job `138359791161`, commit `0bac511abb5370ca286a298f38f83ee7bcbae40b`. Actual WinForms foreground, CopyFromScreen, all pixel sentinels verified. Ubuntu-latest had moved to 26.04, unsupported by Playwright 1.56.1; browser job failed, not counted as PASS.
- Fixed Ubuntu 24.04; second public visual run [45369573507](https://github.com/riyuewuxing/InvestmentEvidenceEngine/actions/runs/45369573507), exact commit `853f39a94d69ce7fbb4b88a1e7714d97ca7ce76d`. Both browser and native jobs SUCCESS. Receiver independently decoded base64, checked actual byte length, PNG signature, dimensions, recomputed SHA256 (known-vector tested), and displayed all three images to the reviewer.
- Browser desktop: two columns, no horizontal overflow, chart visible, actual click state Interaction passed. Mobile: one column, no overflow, chart, button and status visible. Native: readable title, value, button and status, both color sentinels visible; actual window pixels, not DrawToBitmap.

| Frame | Job | Dimensions | Bytes | Observed SHA256 |
| --- | --- | --- | ---: | --- |
| browser-desktop.png | 138360032628 | 1200×760 | 59193 | `33643352f48b7b42a5b0f0088e33e01bf0a684b1630d1f68aa94e87ab15cebe6` |
| browser-mobile.png | 138360032628 | 390×844 | 52200 | `118733a5f79c43c082b083fed9060256f02e000735974a2789f990be99a0106a` |
| windows-native.png | 138360032093 | 800×480 | 12393 | `760c523234cd39a264b005578c0ba69be3e4a81f07f4f6f26e8dfd555a448f62` |

Status: `SYNTHETIC_CAPTURE_TRANSPORT_VALIDATED` at the exact evidence commit above. Public Engine regression of that commit passed 13 tests but Ruff found one import-order issue in emit_png.py; the follow-up fixes ordering and adds an offline receiver plus transport regression tests. Latest commit must be separately checked. No private Actions or Artifact storage used by visual QA. No claim of actual private app UI/EXE build or visual acceptance.

Offline receiver: download the two public job logs, then use `python visual_qa/verify_log.py --commit <full SHA> --run <run ID> --log browser.log --log windows.log --out-dir <new directory>`. Use the observed-byte report and open actual PNGs. This script does not claim visual review merely because its hashes match.

Product integration boundary: public runners may only execute explicitly approved public source/bundle with synthetic data, never checkout private subject or acquire private source via credentials. Reusable workflow hosted in a public repo but called from a private repo does not shift billing to the public repo. Until the source boundary is explicitly resolved, actual product validation remains private/local, and this fixture is not a substitute.
