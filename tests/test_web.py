from io import BytesIO
import hashlib
import json
from pathlib import Path
import time
from uuid import uuid4
import zipfile

import cv2
from api_support import TestClient
import numpy as np
from PIL import Image
import pytest

from local_vision_solver.config import load_config
from api_support import create_app

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def config(tmp_path):
    config = load_config(ROOT / "config.toml")
    config.pipeline.session_directory = tmp_path / "sessions"
    config.server.advertise = False
    return config


def test_site_and_local_connection_qr(config, monkeypatch):
    monkeypatch.setattr("local_vision_solver.server.lan_addresses", lambda: ["172.20.10.2"])
    with TestClient(create_app(config, demo=True)) as client:
        page = client.get("/")
        assert page.status_code == 200 and 'capture="environment"' in page.text
        assert "https://" not in page.text and "http://" not in page.text
        assert "frame-ancestors 'none'" in page.headers["content-security-policy"]
        for file in ["app.js", "style.css", "icon.svg"]:
            assert client.get("/assets/" + file).status_code == 200
        assert client.get("/assets/../config.toml").status_code == 404
        url = client.get("/connection").json()["urls"][0]
        assert url == "http://172.20.10.2:8765/"
        data = client.get("/connection/qr", params={"address": url}).content
        array = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
        assert cv2.QRCodeDetector().detectAndDecode(array)[0] == url
        assert client.get("/connection/qr", params={"address": "https://example.com"}).status_code == 422
        assert client.post("/v1/sessions", json={}, headers={"Origin": "https://example.com"}).status_code == 403
        assert client.post("/v1/sessions", json={}, headers={"Origin": "http://127.0.0.1:8765"}).status_code == 201


def test_heic_preview_original_upload_and_zip_download(config, tmp_path):
    raw = BytesIO()
    Image.new("RGB", (1800, 2200), "white").save(raw, format="HEIF", quality=95)
    data = raw.getvalue()
    with TestClient(create_app(config, demo=True)) as client:
        preview = client.post("/preview", content=data)
        assert preview.status_code == 200
        with Image.open(BytesIO(preview.content)) as image:
            assert image.format == "JPEG" and max(image.size) == 1600
        assert not list(config.pipeline.session_directory.glob("*/incoming/*"))
        identifier = str(uuid4())
        client.post("/v1/sessions", json={"session_id": identifier})
        uploaded = client.put(f"/v1/sessions/{identifier}/pages/1", content=data)
        assert uploaded.status_code == 200, uploaded.text
        record = uploaded.json()
        assert record["file"].endswith(".heic")
        assert record["sha256"] == hashlib.sha256(data).hexdigest()
        original = config.pipeline.session_directory / identifier / "incoming" / record["file"]
        assert original.read_bytes() == data
        client.post(f"/v1/sessions/{identifier}/solve", json={"page_count": 1, "page_order": [1]})
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            status = client.get(f"/v1/sessions/{identifier}").json()
            if status["state"] in {"COMPLETE", "ERROR"}:
                break
            time.sleep(.02)
        assert status["state"] == "COMPLETE", status
        result = client.get(f"/v1/sessions/{identifier}/result").json()
        text = client.get(f"/v1/sessions/{identifier}/answer.txt")
        assert text.text == result["plain_text_answer"]
        assert "attachment" in text.headers["content-disposition"]
        download = client.get(f"/v1/sessions/{identifier}/cards/1?download=true")
        assert "attachment" in download.headers["content-disposition"]
        with zipfile.ZipFile(BytesIO(client.get(f"/v1/sessions/{identifier}/package").content)) as archive:
            assert archive.read("answer.txt").decode("utf-8") == text.text
            manifest = json.loads(archive.read("manifest.json"))
            for card in manifest["cards"]:
                assert hashlib.sha256(archive.read(card["file"])).hexdigest() == card["sha256"]


def test_preview_rejects_invalid_and_oversized_files(config):
    config.server.max_page_megabytes = 1
    with TestClient(create_app(config, demo=True)) as client:
        assert client.post("/preview", content=b"not an image").status_code == 422
        assert client.post("/preview", content=b"x" * (1024**2 + 1)).status_code == 413
        raw = BytesIO()
        Image.new("RGB", (50, 50)).save(raw, format="PNG")
        assert client.post("/preview", content=raw.getvalue()).status_code == 422
