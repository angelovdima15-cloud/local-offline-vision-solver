---
name: vision-checks
description: Select focused checks for the Local Offline Vision Solver backend, mobile local website, renderer, LAN API or portable Windows package; distinguish demo/browser checks from real GPU and iPhone acceptance.
---

# Focused project checks

Use `.venv\Scripts\python.exe scripts/dev.py check <pytest-target>` from the repository root. Full logs are preserved and failure exit codes propagated.

| Changed behavior | Initial check |
| --- | --- |
| Inference stages, retry, context isolation, verification | `tests/test_pipeline.py` |
| Arithmetic, rendering/pagination, endpoint policy, locks | `tests/test_checks_and_rendering.py` |
| Upload, queue, restart, download ZIP integrity | `tests/test_api.py` |
| Website, Origin policy, connection QR, HEIC/preview/downloads | `tests/test_web.py` |
| Bonjour service metadata | `tests/test_discovery.py` |
| Browser UI and recovery | `node --check src/local_vision_solver/web/app.js`, then `scripts/check_browser.py` |

- Run the smallest meaningful target; widen for shared contracts, concurrency, context isolation or a concrete unresolved failure.
- For a real HTTP demo use `scripts/acceptance_http.py`; it owns and stops its isolated child process.
- `scripts/check_browser.py` requires development-only Playwright/Chromium. It exercises desktop/phone viewports, HEIC preview, original bytes/order, lost upload ACK retry, ZIP, reload/disconnect recovery and a new independent task. No external browser requests are allowed.
- `scripts/package_windows.py` freezes the program, includes local web assets and gates the ZIP on a real HTTP test of the frozen EXE. `check_browser.py --executable <exe>` checks the shipped binary UI.
- Native Apple source/builds were removed. Original UX is saved in `docs/native-app-concept.md`; no Swift/Xcode/IPA checks apply to the current product.
- Simulated inference/demo and phone-sized Chromium are not evidence of Qwen accuracy, GPU latency/VRAM, real Safari camera/downloads or iPhone Personal Hotspot connectivity. Hardware steps are in `docs/mvp-acceptance.md`.
- Read complete saved logs for failures; stop optional checking when the concrete risk is covered.
