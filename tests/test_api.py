from io import BytesIO
import json
from pathlib import Path
import threading
import time
from uuid import uuid4

from fastapi.testclient import TestClient
from PIL import Image
import pytest

from local_vision_solver.config import load_config
from local_vision_solver.server import create_app
from local_vision_solver.package import inspect_package

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def config(tmp_path):
    value = load_config(ROOT / "config.toml")
    value.pipeline.session_directory = tmp_path / "sessions"
    value.server.advertise = False
    return value


def photo(color="white"):
    data = BytesIO()
    Image.new("RGB", (600, 800), color).save(data, format="JPEG")
    return data.getvalue()


def create(client, identifier=None):
    response = client.post("/v1/sessions", json={"session_id": str(identifier or uuid4())})
    assert response.status_code == 201, response.text
    return response.json()["session_id"]


def wait(client, identifier):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        state = client.get(f"/v1/sessions/{identifier}").json()
        if state["state"] in {"COMPLETE", "ERROR"}:
            return state
        time.sleep(.01)
    pytest.fail("Worker did not finish")


def submit(client, identifier, pages=1, order=None):
    return client.post(f"/v1/sessions/{identifier}/solve", json={"page_count": pages, "page_order": order or list(range(1, pages+1))})


def test_demo_upload_result_and_atomic_package(config, tmp_path):
    with TestClient(create_app(config, demo=True)) as client:
        assert client.get("/health").json()["demo"] is True
        identifier = create(client)
        for index in (1, 2):
            response = client.put(f"/v1/sessions/{identifier}/pages/{index}", content=photo())
            assert response.status_code == 200
        assert submit(client, identifier, 2).status_code == 202
        assert wait(client, identifier)["state"] == "COMPLETE"
        result = client.get(f"/v1/sessions/{identifier}/result").json()
        assert result["session_id"] == identifier
        assert result["demo"] is True and "No AI solution" in result["plain_text_answer"]
        package = client.get(f"/v1/sessions/{identifier}/package")
        assert package.status_code == 200
        file = tmp_path / "received.lvsp"
        file.write_bytes(package.content)
        header = inspect_package(file)
        assert header["session_id"] == identifier and header["demo"] is True
        assert len(header["cards"]) == len(result["cards"])
        assert client.get(f"/v1/sessions/{identifier}/cards/1").headers["content-type"] == "image/png"
        assert client.delete(f"/v1/sessions/{identifier}").status_code == 204
        assert client.get(f"/v1/sessions/{identifier}").status_code == 404


def test_replayed_create_upload_and_solve_are_idempotent(config):
    with TestClient(create_app(config, demo=True)) as client:
        identifier = create(client)
        assert create(client, identifier) == identifier
        data = photo()
        path = f"/v1/sessions/{identifier}/pages/1"
        first = client.put(path, content=data).json()
        assert client.put(path, content=data).json() == first
        assert client.put(path, content=photo("gray")).status_code == 409
        assert submit(client, identifier).status_code == 202
        assert wait(client, identifier)["state"] == "COMPLETE"
        assert submit(client, identifier).status_code == 202
        assert client.put(path, content=data).status_code == 200
        assert client.put(f"/v1/sessions/{identifier}/pages/2", content=data).status_code == 409


def test_invalid_inputs_and_missing_pages(config):
    with TestClient(create_app(config, demo=True)) as client:
        assert client.get("/v1/sessions/not-a-uuid").status_code == 422
        identifier = create(client)
        assert client.put(f"/v1/sessions/{identifier}/pages/0", content=photo()).status_code == 422
        assert client.put(f"/v1/sessions/{identifier}/pages/1", content=b"not an image").status_code == 422
        assert client.put(f"/v1/sessions/{identifier}/pages/1", content=b"").status_code == 422
        assert submit(client, identifier).status_code == 422
        assert client.get(f"/v1/sessions/{identifier}/package").status_code == 425
        assert client.post(f"/v1/sessions/{identifier}/solve", json={"page_count": 2, "page_order": [1, 1]}).status_code == 422
        assert client.get("/docs").status_code == 404


def test_page_and_session_upload_limits(config):
    config.server.max_page_megabytes = 1
    config.pipeline.max_input_megabytes = 1
    with TestClient(create_app(config, demo=True)) as client:
        identifier = create(client)
        route = f"/v1/sessions/{identifier}/pages/1"
        assert client.put(route, content=b"x"*(1024**2+1)).status_code == 413
        assert not list((config.pipeline.session_directory / identifier / "incoming").glob("*.part"))


def test_gpu_worker_is_serial_and_queue_is_bounded(config):
    started = threading.Event()
    release = threading.Event()
    entered = []

    def blocked(paths, session):
        entered.append(session.id)
        started.set()
        release.wait(5)
        raise RuntimeError("test failure")

    config.server.max_queued_jobs = 1
    with TestClient(create_app(config, runner=blocked)) as client:
        first, second = create(client), create(client)
        for identifier in (first, second):
            client.put(f"/v1/sessions/{identifier}/pages/1", content=photo())
        assert submit(client, first).status_code == 202
        assert started.wait(2)
        assert submit(client, second).status_code == 429
        assert client.delete(f"/v1/sessions/{first}").status_code == 409
        assert entered == [first]
        release.set()
        assert wait(client, first)["state"] == "ERROR"
        assert client.get(f"/v1/sessions/{first}/package").status_code == 425
        assert submit(client, first).status_code == 409
        assert submit(client, second).status_code == 202
        assert wait(client, second)["state"] == "ERROR"


def test_completed_session_survives_backend_restart(config):
    with TestClient(create_app(config, demo=True)) as client:
        identifier = create(client)
        client.put(f"/v1/sessions/{identifier}/pages/1", content=photo())
        submit(client, identifier)
        assert wait(client, identifier)["state"] == "COMPLETE"
    with TestClient(create_app(config, demo=True)) as client:
        assert client.get(f"/v1/sessions/{identifier}").json()["state"] == "COMPLETE"
        assert client.get(f"/v1/sessions/{identifier}/package").status_code == 200


def test_interrupted_job_is_not_reported_as_complete(config):
    with TestClient(create_app(config, demo=True)) as client:
        identifier = create(client)
    path = config.pipeline.session_directory / identifier / "job.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["state"] = "RUNNING"
    path.write_text(json.dumps(data), encoding="utf-8")
    with TestClient(create_app(config, demo=True)) as client:
        status = client.get(f"/v1/sessions/{identifier}").json()
        assert status["state"] == "ERROR" and status["error"]["code"] == "interrupted"


def test_package_corruption_is_detected(config, tmp_path):
    with TestClient(create_app(config, demo=True)) as client:
        identifier = create(client)
        client.put(f"/v1/sessions/{identifier}/pages/1", content=photo())
        submit(client, identifier)
        wait(client, identifier)
        data = bytearray(client.get(f"/v1/sessions/{identifier}/package").content)
    data[-1] ^= 0xFF
    file = tmp_path / "corrupt.lvsp"
    file.write_bytes(data)
    with pytest.raises(ValueError, match="integrity"):
        inspect_package(file)

