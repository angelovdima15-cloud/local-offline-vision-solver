from pathlib import Path
from urllib.parse import urlparse
import json
import subprocess

from .config import Config
from .resources import gpu_snapshot


def server_command(config: Config) -> list[str]:
    runtime = config.runtime
    endpoint = urlparse(config.inference.endpoint)
    args = [str(runtime.executable), "--model", str(runtime.model), "--mmproj", str(runtime.projector),
            "--alias", config.inference.model_alias, "--host", str(endpoint.hostname),
            "--port", str(endpoint.port or 80), "--ctx-size", str(runtime.context_size),
            "--n-gpu-layers", str(runtime.gpu_layers), "--fit", "on",
            "--fit-target", str(runtime.vram_margin_megabytes),
            "--batch-size", str(runtime.batch_size), "--ubatch-size", str(runtime.micro_batch_size),
            "--flash-attn", runtime.flash_attention, "--cache-type-k", runtime.kv_cache_type,
            "--cache-type-v", runtime.kv_cache_type, "--parallel", "1", "--jinja",
            "--no-context-shift", "--cache-ram", "0", "--slots", "--offline", "--no-webui"]
    if not runtime.projector_on_gpu:
        args.append("--no-mmproj-offload")
    return args


def start_server(config: Config) -> int:
    process = launch_server(config)
    try:
        return process.wait()
    except KeyboardInterrupt:
        stop_server(process)
        return 130


def launch_server(config: Config) -> subprocess.Popen:
    for name in ("executable", "model", "projector"):
        value = getattr(config.runtime, name)
        if not value.is_file():
            raise FileNotFoundError(f"Missing {name}: {value}. Run installation on the target laptop first.")
    args = server_command(config)
    # Never restart after OOM with silently weakened quantization/context/image resolution.
    # The user can explicitly select a reviewed runtime profile and benchmark it.
    log = config.runtime.executable.parent / "server.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    print(f"Local inference: {config.inference.endpoint}; startup log: {log}", flush=True)
    with log.open("a", encoding="utf-8") as handle:
        handle.write("\nSTART " + json.dumps(args) + "\n")
        handle.flush()
        return subprocess.Popen(args, stdout=handle, stderr=subprocess.STDOUT)


def stop_server(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def inspect_environment(config: Config) -> dict:
    files = {name: {"path": str(getattr(config.runtime, name)),
                    "exists": getattr(config.runtime, name).is_file()}
             for name in ("executable", "model", "projector")}
    report = {"gpu": gpu_snapshot(), "files": files,
              "fonts": {"text": config.render.font_path.is_file(), "code": config.render.code_font_path.is_file()},
              "math_engine": config.render.math_engine, "launch_command": server_command(config)}
    from .inference import InferenceError, LocalModel
    with LocalModel(config.inference) as model:
        try:
            report["inference"] = model.health()
        except InferenceError as exc:
            report["inference"] = {"status": "unavailable", "message": str(exc)}
    report["ready"] = (all(f["exists"] for f in files.values()) and all(report["fonts"].values())
                       and report["inference"].get("status") == "ok")
    return report
