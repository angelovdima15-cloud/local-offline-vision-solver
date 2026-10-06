"""Assemble prebuilt binaries for handoff; do not include source or local sessions."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import plistlib
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    dist = ROOT / "dist"
    windows = dist / "LocalVisionSolver-Windows-x64.zip"
    ipa = dist / "LocalVisionSolver-unsigned.ipa"
    with zipfile.ZipFile(windows) as archive:
        manifest = json.loads(archive.read("LocalVisionSolver/PACKAGE-MANIFEST.json"))
        assert manifest["frozen_http_transport_check"] == "passed"
        for name, expected in manifest["files"].items():
            assert hashlib.sha256(archive.read("LocalVisionSolver/" + name)).hexdigest() == expected, name
    with zipfile.ZipFile(ipa) as archive:
        phone = plistlib.loads(archive.read("Payload/VisionPhone.app/Info.plist"))
        watch = plistlib.loads(archive.read("Payload/VisionPhone.app/Watch/VisionWatch.app/Info.plist"))
        assert watch["WKCompanionAppBundleIdentifier"] == phone["CFBundleIdentifier"]
        for prefix, info in [("Payload/VisionPhone.app/", phone), ("Payload/VisionPhone.app/Watch/VisionWatch.app/", watch)]:
            assert prefix + info["CFBundleExecutable"] in archive.namelist()
    files = [windows, windows.with_suffix(".zip.sha256"), ipa, ipa.with_suffix(".ipa.sha256")]
    handoff = {"version": "0.2.0", "kind": "prebuilt installation and hardware acceptance package",
               "signed_apple_app": False, "model_weights_included": False,
               "production_accepted": False,
               "checks": ["45 Python tests", "5 Swift tests", "iPhone/watchOS simulator builds",
                          "device IPA build and companion IDs", "frozen Windows HTTP demo"],
               "pending": ["Apple device signing and installation", "real WatchConnectivity delivery",
                           "Qwen answer accuracy and latency on RTX 4060 Laptop 8 GB"],
               "files": {f.name: hashlib.sha256(f.read_bytes()).hexdigest() for f in files}}
    destination = dist / "LocalVisionSolver-Customer.zip"
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_STORED) as archive:
        for file in files:
            archive.write(file, file.name)
        archive.write(ROOT / "docs/customer-start.md", "START-HERE.md")
        archive.writestr("DELIVERY-MANIFEST.json", json.dumps(handoff, indent=2) + "\n")
    digest = hashlib.sha256(destination.read_bytes()).hexdigest()
    destination.with_suffix(".zip.sha256").write_text(digest + "  " + destination.name + "\n", encoding="ascii")
    print(f"Customer package: {destination}; bytes={destination.stat().st_size}; sha256={digest}")


if __name__ == "__main__":
    main()
