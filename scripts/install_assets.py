"""Online initial installation ONLY. No runtime module imports this script."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
import time
from urllib.request import Request, urlopen
from urllib.error import HTTPError
import zipfile

ROOT = Path(__file__).resolve().parents[1]
RELEASE = "b11429"
RUNTIME_FILES = {
    f"llama-{RELEASE}-bin-win-cuda-12.4-x64.zip": "dd6df685c1024e6aa55ca55ad35038692d5e284d4dc895e7a646c3245d3d14ff",
    "cudart-llama-bin-win-cuda-12.4-x64.zip": "8c79a9b226de4b3cacfd1f83d24f962d0773be79f1e7b75c6af4ded7e32ae1d6",
}
REPOSITORY = "Qwen/Qwen3-VL-8B-Instruct-GGUF"


def file_hash(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def download(url: str, destination: Path, expected_sha: str, expected_size: int | None = None) -> dict:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if file_hash(destination) != expected_sha:
            raise RuntimeError(f"Existing file has unexpected hash: {destination}. Inspect it before replacing.")
        print(f"Verified existing {destination.name}", flush=True)
        return {"file": destination.name, "url": url, "sha256": expected_sha, "bytes": destination.stat().st_size}
    partial = destination.with_suffix(destination.suffix + ".part")
    existing = partial.stat().st_size if partial.exists() else 0
    headers = {"User-Agent": "LocalOfflineVisionSolver-Setup/0.1"}
    if existing:
        headers["Range"] = f"bytes={existing}-"
    try:
        response = urlopen(Request(url, headers=headers), timeout=90)
    except HTTPError as exc:
        if exc.code == 416 and partial.exists() and file_hash(partial) == expected_sha:
            partial.replace(destination)
            return {"file": destination.name, "url": url, "sha256": expected_sha, "bytes": destination.stat().st_size}
        raise
    with response:
        append = existing > 0 and response.status == 206
        if append and not response.headers.get("Content-Range", "").startswith(f"bytes {existing}-"):
            raise RuntimeError("Invalid download resume range")
        received = existing if append else 0
        last_report = 0.0
        with partial.open("ab" if append else "wb") as handle:
            while chunk := response.read(4 * 1024**2):
                handle.write(chunk)
                received += len(chunk)
                if time.monotonic() - last_report >= 5:
                    print(f"{destination.name}: {received / 1024**2:.0f} MiB", flush=True)
                    last_report = time.monotonic()
    if expected_size is not None and partial.stat().st_size != expected_size:
        raise RuntimeError(f"Download size mismatch for {destination.name}; partial retained")
    if file_hash(partial) != expected_sha:
        raise RuntimeError(f"SHA256 mismatch for {destination.name}; partial retained for inspection")
    partial.replace(destination)
    return {"file": destination.name, "url": url, "sha256": expected_sha, "bytes": destination.stat().st_size}


def extract_flat(archive: Path, destination: Path) -> None:
    # Only expected executables/DLLs from the checked archive; flatten without archive paths.
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as package:
        for member in package.infolist():
            name = Path(member.filename).name
            if member.is_dir() or Path(name).suffix.lower() not in {".exe", ".dll"}:
                continue
            output = destination / name
            if output.resolve().parent != destination.resolve():
                raise RuntimeError("Unsafe runtime archive entry")
            with package.open(member) as source, output.open("wb") as target:
                shutil.copyfileobj(source, target)


def install(args) -> None:
    records = []
    if not args.models_only:
        for name, sha in RUNTIME_FILES.items():
            archive = ROOT / ".cache" / "downloads" / name
            records.append(download(f"https://github.com/ggml-org/llama.cpp/releases/download/{RELEASE}/{name}",
                                    archive, sha))
            extract_flat(archive, ROOT / "runtime" / "llama")
        if not (ROOT / "runtime" / "llama" / "llama-server.exe").is_file():
            raise RuntimeError("Runtime archive contained no llama-server.exe")
    if not args.runtime_only:
        request = Request(f"https://huggingface.co/api/models/{REPOSITORY}?blobs=true",
                          headers={"User-Agent": "LocalOfflineVisionSolver-Setup/0.1"})
        with urlopen(request, timeout=30) as response:
            metadata = json.load(response)
        revision = metadata["sha"]
        files = {item["rfilename"]: item for item in metadata["siblings"]}
        selected = [f"Qwen3VL-8B-Instruct-{args.quantization}.gguf",
                    f"mmproj-Qwen3VL-8B-Instruct-{args.projector}.gguf"]
        for name in selected:
            info = files[name]
            lfs = info["lfs"]
            record = download(f"https://huggingface.co/{REPOSITORY}/resolve/{revision}/{name}",
                              ROOT / "models" / name, lfs["sha256"], lfs["size"])
            record["repository_revision"] = revision
            records.append(record)
    record_path = ROOT / "runtime" / "install-record.json"
    record_path.parent.mkdir(parents=True, exist_ok=True)
    prior = json.loads(record_path.read_text(encoding="utf-8")) if record_path.exists() else {"assets": []}
    prior["llama_release"] = RELEASE
    prior["assets"].extend(records)
    record_path.write_text(json.dumps(prior, indent=2), encoding="utf-8")
    print(f"Installed and verified assets. Record: {record_path}")
    print("Runtime startup is offline. Any nondefault model/projector requires updating config.toml.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Initial Internet installation of local CUDA runtime and model assets")
    parser.add_argument("--quantization", choices=["Q4_K_M", "Q8_0", "F16"], default="Q4_K_M")
    parser.add_argument("--projector", choices=["F16", "Q8_0"], default="F16")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--runtime-only", action="store_true")
    group.add_argument("--models-only", action="store_true")
    args = parser.parse_args()
    try:
        install(args)
        return 0
    except (OSError, RuntimeError, KeyError, ValueError) as exc:
        print(f"Installation failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

