import json
from pathlib import Path

import httpx
from PIL import Image, ImageDraw
import pytest

from local_vision_solver.config import load_config
from local_vision_solver.inference import LocalModel, InferenceError
from local_vision_solver.models import Reading
from local_vision_solver.pipeline import Pipeline, PipelineError
import local_vision_solver.pipeline as pipeline_module
import local_vision_solver.resources as resources_module

ROOT = Path(__file__).resolve().parents[1]


def reading(page_count=1, **changes):
    value = {"detected_language": "ru", "subject": "mathematics", "task_type": "algebra",
             "requires_math_rendering": True, "page_order": list(range(1, page_count + 1)),
             "problem_text": "3x + 4 = 40", "questions": [{"id": "1", "text": "Решите уравнение",
                                                             "page_numbers": [1]}],
             "uncertainties": [], "sufficient_information": True, "warnings": []}
    return value | changes


def draft(**changes):
    value = json.loads((ROOT / "examples" / "answer_math.json").read_text(encoding="utf-8"))
    value["warnings"] = []
    return value | changes


def audit(**changes):
    return {"verdict": "accept", "question_understanding_checked": True,
            "all_questions_answered": True, "units_checked": True, "answer_options_checked": True,
            "original_images_checked": True, "issues": [], "correction_instructions": ""} | changes


class FakeInference:
    """Exercises real HTTP adapter; these deterministic answers are NOT model accuracy tests."""
    def __init__(self):
        self.requests = []
        self.readings = []
        self.drafts = []
        self.audits = []
        self.finishes = []
        self.erase_count = 0
        self.page_count = 1

    def handle(self, request):
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        if request.url.path == "/slots/0":
            assert request.url.params["action"] == "erase"
            self.erase_count += 1
            return httpx.Response(200, json={"n_erased": 100})
        assert request.url.path == "/v1/chat/completions"
        value = json.loads(request.content)
        self.requests.append(value)
        name = value["response_format"]["schema"]["title"]
        if name == "Reading":
            output = self.readings.pop(0) if self.readings else reading(self.page_count)
        elif name == "Draft":
            output = self.drafts.pop(0) if self.drafts else draft()
        elif name == "Audit":
            output = self.audits.pop(0) if self.audits else audit()
        else:
            raise AssertionError(name)
        finish = self.finishes.pop(0) if self.finishes else "stop"
        return httpx.Response(200, json={"choices": [{"finish_reason": finish,
                           "message": {"content": json.dumps(output, ensure_ascii=False)}}],
                           "usage": {"prompt_tokens": 100, "completion_tokens": 100}})


@pytest.fixture
def environment(tmp_path, monkeypatch):
    config = load_config(ROOT / "config.toml")
    config.pipeline.session_directory = tmp_path / "sessions"
    config.pipeline.max_corrections = 1
    monkeypatch.setattr(resources_module, "gpu_snapshot", lambda: [])
    image = tmp_path / "page.jpg"
    canvas = Image.new("RGB", (1200, 1600), "white")
    draw = ImageDraw.Draw(canvas)
    draw.text((80, 100), "3x + 4 = 40", fill="black", font_size=64)
    canvas.save(image)
    server = FakeInference()

    class Model(LocalModel):
        def __init__(self, settings, session=None):
            super().__init__(settings, session, transport=httpx.MockTransport(server.handle))

    monkeypatch.setattr(pipeline_module, "LocalModel", Model)
    return config, image, server


def test_complete_pipeline_keeps_originals_and_verifies_before_cards(environment):
    config, image, server = environment
    session, result = Pipeline(config).solve([image])
    assert result["status"] == "complete"
    assert (session.path / "originals" / "page_01.jpg").read_bytes() == image.read_bytes()
    assert result["verification"]["independent_pass_completed"]
    assert all(c["passed"] for c in result["verification"]["numeric_checks"])
    assert len(result["cards"]) == 2
    assert server.erase_count == 2
    independent_prompt = server.requests[2]["messages"][1]["content"][0]["text"]
    assert "Independently re-read" in independent_prompt
    assert "x = 12" not in independent_prompt
    assert "Candidate:" not in independent_prompt
    states = [json.loads(line)["state"] for line in (session.path / "events.jsonl").read_text(encoding="utf-8").splitlines()]
    assert states.index("VERIFYING_AUDIT") < states.index("RENDERING") < states.index("COMPLETE")


def test_sessions_share_no_previous_images_or_messages(environment, tmp_path):
    config, image, server = environment
    pipeline = Pipeline(config)
    first, _ = pipeline.solve([image])
    first_requests = list(server.requests)
    other = tmp_path / "second.jpg"
    Image.new("RGB", (1200, 1600), "gray").save(other)
    server.requests.clear()
    second, _ = pipeline.solve([other])
    assert first.id != second.id
    assert server.erase_count == 4
    previous_images = {item["image_url"]["url"] for request in first_requests
                       for item in request["messages"][1]["content"] if item["type"] == "image_url"}
    for request in server.requests:
        assert len(request["messages"]) == 2
        assert request["cache_prompt"] is False
        images = [item["image_url"]["url"] for item in request["messages"][1]["content"]
                  if item["type"] == "image_url"]
        assert not previous_images.intersection(images)


def test_every_inference_stage_receives_all_pages(environment, tmp_path):
    config, image, server = environment
    second = tmp_path / "page2.jpg"
    Image.new("RGB", (1200, 1600), "white").save(second)
    server.page_count = 2
    session, result = Pipeline(config).solve([image, second])
    assert result["page_order"] == [1, 2]
    for request in server.requests:
        content = request["messages"][1]["content"]
        labels = [item["text"] for item in content if item["type"] == "text"]
        assert "ORIGINAL PAGE 1 of 2" in labels and "ORIGINAL PAGE 2 of 2" in labels
        assert sum(item["type"] == "image_url" for item in content) >= 2


def test_failed_arithmetic_blocks_even_an_accepting_model(environment):
    config, image, server = environment
    bad = draft(numeric_checks=[{"label": "wrong", "left": "3 * 12 + 4", "right": "41", "absolute_tolerance": 0}])
    server.drafts = [bad, draft(), bad]
    with pytest.raises(PipelineError, match="Verification did not establish") as captured:
        Pipeline(config).solve([image])
    assert captured.value.code == "verification_failed"
    assert not (captured.value.session.path / "cards").exists()
    assert not (captured.value.session.path / "result.json").exists()
    assert server.erase_count == 2


def test_correction_is_audited_again_before_delivery(environment):
    config, image, server = environment
    server.audits = [audit(verdict="revise", issues=["Arithmetic error"], correction_instructions="Recalculate"), audit()]
    session, result = Pipeline(config).solve([image])
    assert result["status"] == "complete"
    assert len([r for r in server.requests if r["response_format"]["schema"]["title"] == "Audit"]) == 2
    assert (session.path / "candidate_01.json").exists()


def test_unanswered_subquestion_cannot_be_delivered(environment):
    config, image, server = environment
    server.readings = [reading(questions=[{"id": "1", "text": "First", "page_numbers": [1]},
                                         {"id": "2", "text": "Second", "page_numbers": [1]}])]
    with pytest.raises(PipelineError) as captured:
        Pipeline(config).solve([image])
    assert captured.value.code == "verification_failed"
    assert not (captured.value.session.path / "cards").exists()


def test_ambiguity_recovers_from_original_crop(environment):
    config, image, server = environment
    server.readings = [reading(uncertainties=[{"page_number": 1, "description": "3 or 8",
                       "alternatives": ["3", "8"], "crop_box": [.02, .02, .3, .2]}]), reading()]
    session, _ = Pipeline(config).solve([image])
    retry = server.requests[1]["messages"][1]["content"]
    assert any("Detail crop of ORIGINAL PAGE 1" in v.get("text", "") for v in retry)
    assert (session.path / "processed" / "retry_00_page_01.png").exists()


def test_missing_information_retries_before_retake(environment):
    config, image, server = environment
    server.readings = [reading(sufficient_information=False), reading(sufficient_information=False)]
    with pytest.raises(PipelineError) as captured:
        Pipeline(config).solve([image])
    assert captured.value.code == "retake_required"
    assert len(server.requests) == 2
    assert not (captured.value.session.path / "cards").exists()


def test_truncated_model_output_retries_with_larger_budget(environment):
    config, image, server = environment
    server.finishes = ["length", "stop"]
    session, _ = Pipeline(config).solve([image])
    assert server.requests[0]["max_tokens"] * 2 == server.requests[1]["max_tokens"]
    assert len(server.requests[1]["messages"]) == 2


def test_output_still_truncated_at_limit_is_not_delivered(environment):
    config, image, server = environment
    server.finishes = ["length", "length"]
    with pytest.raises(PipelineError, match="exceeded output limit") as captured:
        Pipeline(config).solve([image])
    assert not (captured.value.session.path / "result.json").exists()


def test_no_result_is_released_if_context_erase_fails(environment, monkeypatch):
    config, image, _ = environment
    cls = pipeline_module.LocalModel
    original = cls.clear_context
    calls = []

    def fail_at_end(self):
        calls.append(True)
        if len(calls) >= 2:
            raise InferenceError("context erase failed")
        original(self)

    monkeypatch.setattr(cls, "clear_context", fail_at_end)
    with pytest.raises(PipelineError, match="context erase failed") as captured:
        Pipeline(config).solve([image])
    assert not (captured.value.session.path / "result.json").exists()


def test_http_job_runs_real_pipeline_adapter_before_packaging(environment, tmp_path):
    import time
    from fastapi.testclient import TestClient
    from local_vision_solver.server import create_app
    from local_vision_solver.package import inspect_package
    config, image, server = environment
    with TestClient(create_app(config, advertise=False)) as client:
        identifier = client.post("/v1/sessions", json={}).json()["session_id"]
        upload = client.put(f"/v1/sessions/{identifier}/pages/1", content=image.read_bytes())
        assert upload.status_code == 200
        assert client.post(f"/v1/sessions/{identifier}/solve", json={"page_count": 1, "page_order": [1]}).status_code == 202
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            status = client.get(f"/v1/sessions/{identifier}").json()
            if status["state"] in {"COMPLETE", "ERROR"}: break
            time.sleep(.01)
        assert status["state"] == "COMPLETE", status
        result = client.get(f"/v1/sessions/{identifier}/result").json()
        assert result["verification"]["independent_pass_completed"]
        assert result["verification"]["audit"]["verdict"] == "accept"
        assert server.erase_count == 2
        file = tmp_path / "verified.lvsp"
        file.write_bytes(client.get(f"/v1/sessions/{identifier}/package").content)
        header = inspect_package(file)
        assert header["demo"] is False and header["session_id"] == identifier
        assert len(header["cards"]) == 2
