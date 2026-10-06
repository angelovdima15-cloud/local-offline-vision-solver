"""Create a source-only customer archive from an allowlist; exclude local/private data."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
TREES = ("src", "scripts", "tests", "apple", "docs", "examples", "benchmarks", "tools/codex", ".github")
FILES = ("README.md", "DELIVERY.md", "AGENTS.md", "config.toml", "pyproject.toml", "requirements.lock.txt",
         ".gitignore", ".ignore", "setup.cmd", "start-backend.cmd", "start-demo.cmd")
EXCLUDED_DIRS = {"__pycache__", ".build", ".swiftpm", "xcuserdata", "private"}
EXCLUDED_FILES = {"Signing.local.xcconfig", "config.local.toml", "manifest.local.json"}


def selected_files() -> list[Path]:
    files = [ROOT / name for name in FILES]
    for name in TREES:
        for file in (ROOT / name).rglob("*"):
            relative = file.relative_to(ROOT)
            if (file.is_file() and not file.is_symlink() and
                    not EXCLUDED_DIRS.intersection(relative.parts) and
                    not any(part.endswith(".egg-info") for part in relative.parts) and
                    file.name not in EXCLUDED_FILES and file.suffix not in {".pyc", ".pyo"}):
                if not file.resolve().is_relative_to(ROOT.resolve()):
                    raise ValueError("Source path points outside workspace")
                files.append(file)
    return sorted(set(files))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "dist" / "LocalVisionSolver-MVP-source.zip")
    args = parser.parse_args()
    output = args.output.resolve()
    files = selected_files()
    for file in files:
        if not file.is_file():
            raise ValueError(f"Required source file missing: {file}")
    manifest = {"created_at": datetime.now(timezone.utc).isoformat(), "kind": "MVP source handoff",
                "production_accepted": False, "signed_apple_apps_included": False,
                "model_assets_included": False,
                "files": {file.relative_to(ROOT).as_posix(): hashlib.sha256(file.read_bytes()).hexdigest() for file in files}}
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for file in files:
            archive.write(file, "LocalVisionSolver/" + file.relative_to(ROOT).as_posix())
        archive.writestr("LocalVisionSolver/SOURCE_MANIFEST.json", json.dumps(manifest, indent=2) + "\n")
    checksum = hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_suffix(".zip.sha256").write_text(f"{checksum}  {output.name}\n", encoding="utf-8")
    print(f"source archive: {output}; files={len(files)}; bytes={output.stat().st_size}; sha256={checksum}")


if __name__ == "__main__":
    main()
