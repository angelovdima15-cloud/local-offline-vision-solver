"""Exercise a real HTTP demo service without a model or Internet."""
import argparse
from io import BytesIO
import json
from pathlib import Path
import time
from uuid import uuid4

import httpx
from PIL import Image, ImageDraw

from local_vision_solver.package import inspect_package


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8765")
    parser.add_argument("--output", type=Path, default=Path(".cache/transport-smoke"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    with httpx.Client(base_url=args.url, trust_env=False, follow_redirects=False, timeout=15) as client:
        health = client.get("/health")
        health.raise_for_status()
        if not health.json().get("demo"):
            raise RuntimeError("Smoke test requires serve --demo; no photographed task is solved")
        identifier = str(uuid4())
        response = client.post("/v1/sessions", json={"session_id": identifier})
        response.raise_for_status()
        for index in (1, 2):
            image = Image.new("RGB", (1200, 1600), "white")
            ImageDraw.Draw(image).text((80, 100), f"TRANSPORT DEMO PAGE {index}", fill="black", font_size=60)
            data = BytesIO(); image.save(data, format="JPEG", quality=95)
            upload = client.put(f"/v1/sessions/{identifier}/pages/{index}", content=data.getvalue())
            upload.raise_for_status()
        response = client.post(f"/v1/sessions/{identifier}/solve", json={"page_count": 2, "page_order": [1, 2]})
        response.raise_for_status()
        deadline = time.monotonic() + 30
        states = []
        while time.monotonic() < deadline:
            status = client.get(f"/v1/sessions/{identifier}").json()
            states.append(status["state"])
            if status["state"] == "ERROR": raise RuntimeError(status["error"])
            if status["result_available"]: break
            time.sleep(.1)
        else: raise RuntimeError("Demo processing timeout")
        package = client.get(f"/v1/sessions/{identifier}/package")
        package.raise_for_status()
        file = args.output / "result.lvsp"
        file.write_bytes(package.content)
        header = inspect_package(file)
        assert header["session_id"] == identifier and header["demo"]
        card = client.get(f"/v1/sessions/{identifier}/cards/1")
        card.raise_for_status()
        (args.output / "answer_01.png").write_bytes(card.content)
        report = {"session_id": identifier, "transport": "real HTTP", "pages_uploaded": 2,
                  "cards": len(header["cards"]), "checksum_verified": True, "demo": True, "states": states}
        (args.output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report, indent=2))
        client.delete(f"/v1/sessions/{identifier}").raise_for_status()


if __name__ == "__main__":
    main()

