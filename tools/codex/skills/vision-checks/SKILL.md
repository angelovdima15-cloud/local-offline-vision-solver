---
name: vision-checks
description: Select focused checks for changes to Local Offline Vision Solver backend, renderer, LAN protocol, or Apple companion apps; distinguish simulated tests from hardware validation.
---

# Focused project checks

Run from the repository root with `.venv\Scripts\python.exe scripts/dev.py check <pytest-target>`. The helper preserves full logs and propagates the child exit code.

| Changed behavior | Initial test target |
| --- | --- |
| Inference stages, retry, context isolation, solution gates | `tests/test_pipeline.py` |
| Arithmetic, endpoint policy, rendering/pagination, locks | `tests/test_checks_and_rendering.py` |
| Upload, queue, restart, result package | `tests/test_api.py` |
| Bonjour service metadata | `tests/test_discovery.py` |
| Apple project structure or shared fixture | `tests/test_apple_project.py` |

- Select individual `file.py::test_name` nodes for isolated changes; expand when the change affects more behavior.
- A framing/protocol change touches Python `package.py` and Swift `ResultPackage.swift`: check both Python API tests and Apple package tests. Update the fixture only when the protocol intentionally changes.
- Native compilation: on macOS run `bash scripts/check-apple.sh`. Windows cannot verify Xcode compilation.
- Actual LAN/device acceptance and offline operation are specified in `docs/mvp-acceptance.md`; read the relevant section when that is the task.
- For an actual HTTP transport check, use `scripts/smoke_api.py --help` and a running demo backend. Demo explicitly does not solve photographs.
- Simulated inference and transport tests cannot establish model accuracy, timing, VRAM suitability, camera quality, or paired Watch delivery.
- Read the full saved log when the compact failure excerpt is insufficient; never infer success from filtered output.
