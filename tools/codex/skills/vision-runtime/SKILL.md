---
name: vision-runtime
description: Configure or benchmark this project's local Qwen3-VL/llama.cpp Windows deployment and diagnose model startup, GPU memory, or offline installation problems.
---

# Local model deployment

- Deployment target: RTX 4060 Laptop 8 GB. The development laptop has RTX 3050 4 GB; do not treat its measurements as acceptance for the target.
- `config.toml` defines inference/renderer/LAN settings; `config.local.toml` is the local override. Inspect only settings relevant to the request.
- Use `.venv\Scripts\vision-solver.exe --help` and the specific subcommand help for current arguments.
- `scripts/setup.ps1` installs dependencies; `-DownloadAssets` additionally downloads the pinned official runtime/model assets. Internet is allowed for initial installation only.
- `scripts/start-backend.ps1` starts the local model and LAN server. `-Demo` tests transport/rendering without AI; `-ExternalModel` uses an already running local model.
- Preserve the loopback-only llama endpoint, fresh per-session messages, context erase gates, original images, independent verification, and bounded single GPU queue.
- Q4 is a candidate, not a proven accuracy winner. Benchmark real task photographs across the required subjects before selecting quantization. Use the actual CLI benchmark command and `benchmarks/` manifest format.
- Keep Qwen API traffic local; use the original images for ambiguous readings. No external OCR or cloud model fallback.
- Read `docs/validation.md` for recorded evidence or `docs/mvp-acceptance.md` for hardware acceptance only when the task requires it.
- Report measured timing, device memory, workload/page count, quantization, and correctness review separately. A successful model load is not answer-quality acceptance.
