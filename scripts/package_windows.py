"""Build a portable Windows package; model assets are installed separately."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    if os.name != "nt":
        raise RuntimeError("Build this package on Windows")
    # A new directory avoids overwriting any existing customer files or model assets.
    stage = ROOT / ".cache" / "portable-build"
    stage.mkdir(parents=True, exist_ok=False)
    build = stage / "build"
    dist = stage / "dist"
    common = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
              "--distpath", str(dist), "--workpath", str(build), "--specpath", str(stage)]
    log = stage / "build.log"
    with log.open("w", encoding="utf-8") as output:
        for options in (
            ["--onedir", "--name", "vision-backend", "--paths", str(ROOT / "src"),
             "--collect-submodules", "uvicorn", "--collect-submodules", "zeroconf",
             "--recursive-copy-metadata", "local-offline-vision-solver",
             str(ROOT / "scripts" / "frozen_backend.py")],
            ["--onefile", "--name", "install-assets", str(ROOT / "scripts" / "install_assets.py")],
        ):
            subprocess.run([*common, *options], cwd=ROOT, stdout=output, stderr=subprocess.STDOUT, check=True)
    package = dist / "vision-backend"
    shutil.copy2(dist / "install-assets.exe", package / "install-assets.exe")
    shutil.copy2(ROOT / "config.toml", package / "config.toml")
    shutil.copy2(ROOT / "docs" / "customer-start.md", package / "START-HERE.md")
    commands = {
        "Initial-Setup.cmd": 'install-assets.exe\n',
        "Start.cmd": 'vision-backend.exe --config config.toml serve\n',
        "Check.cmd": 'vision-backend.exe --config config.toml doctor\n',
        "Transport-Demo.cmd": 'vision-backend.exe --config config.toml serve --demo\n',
    }
    for name, command in commands.items():
        (package / name).write_text('@echo off\ncd /d "%~dp0"\n' + command + 'set "vision_exit=%errorlevel%"\npause\nexit /b %vision_exit%\n', encoding="ascii")
    # This gate exercises only the frozen executable, including its renderer and native DLLs.
    subprocess.run([sys.executable, "scripts/acceptance_http.py", "--executable",
                    str(package / "vision-backend.exe")], cwd=ROOT, check=True)
    subprocess.run([str(package / "install-assets.exe"), "--help"], cwd=package, check=True)
    manifest = {"kind": "portable Windows x64 backend", "version": "0.2.0",
                "model_assets_included": False, "hardware_acceptance_complete": False,
                "frozen_http_transport_check": "passed",
                "files": {f.relative_to(package).as_posix(): hashlib.file_digest(f.open("rb"), "sha256").hexdigest()
                          for f in sorted(package.rglob("*")) if f.is_file()}}
    (package / "PACKAGE-MANIFEST.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    destination = ROOT / "dist" / "LocalVisionSolver-Windows-x64.zip"
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for file in sorted(package.rglob("*")):
            if file.is_file():
                archive.write(file, "LocalVisionSolver/" + file.relative_to(package).as_posix())
    with destination.open("rb") as handle:
        checksum = hashlib.file_digest(handle, "sha256").hexdigest()
    destination.with_suffix(".zip.sha256").write_text(f"{checksum}  {destination.name}\n", encoding="ascii")
    print(f"Portable package: {destination}; bytes={destination.stat().st_size}; sha256={checksum}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
