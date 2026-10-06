from contextlib import asynccontextmanager
from dataclasses import dataclass, field
import asyncio
import hashlib
import json
import logging
from pathlib import Path
import queue
import shutil
import threading
import time
from uuid import UUID

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from PIL import Image
from pydantic import Field

from .config import Config, StrictModel
from .discovery import Advertisement
from .inference import LocalModel, InferenceError
from .package import build_package
from .pipeline import Pipeline, PipelineError
from .storage import Session, write_json

logger = logging.getLogger("vision.service")


class CreateSession(StrictModel):
    session_id: UUID | None = None


class SubmitTask(StrictModel):
    page_count: int = Field(ge=1, le=100)
    page_order: list[int] = Field(min_length=1, max_length=100)


@dataclass
class Job:
    session: Session
    created_at: float
    state: str = "RECEIVING"
    pages: dict[int, dict] = field(default_factory=dict)
    order: list[int] = field(default_factory=list)
    error: dict | None = None
    upload_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def persist(self):
        write_json(self.session.path / "job.json", {
            "session_id": self.session.id, "created_at": self.created_at, "state": self.state,
            "pages": {str(k): v for k, v in self.pages.items()}, "page_order": self.order, "error": self.error})


class JobManager:
    def __init__(self, config: Config, runner=None, *, demo: bool = False):
        self.config = config
        self.demo = demo
        self.runner = runner or (lambda paths, session: Pipeline(config).solve(paths, session=session)[1])
        self.jobs: dict[str, Job] = {}
        self.guard = threading.RLock()
        self.pending: queue.Queue[str | None] = queue.Queue()
        self.stop = threading.Event()
        self.worker = threading.Thread(target=self._work, name="vision-gpu-worker", daemon=True)

    def start(self):
        root = self.config.pipeline.session_directory
        root.mkdir(parents=True, exist_ok=True)
        for metadata_path in root.glob("*/job.json"):
            try:
                data = json.loads(metadata_path.read_text(encoding="utf-8"))
                session = Session(root, data["session_id"], restore=True)
                job = Job(session, data["created_at"], data["state"],
                          {int(k): v for k, v in data["pages"].items()}, data["page_order"], data["error"])
                if job.state == "RUNNING":
                    job.state = "ERROR"
                    job.error = {"code": "interrupted", "message": "Backend restarted during processing. Retry as a new task."}
                    session.event("ERROR", **job.error)
                    job.persist()
                if job.state == "COMPLETE" and not (session.path / "result.lvsp").is_file():
                    job.state = "ERROR"
                    job.error = {"code": "package_missing", "message": "Stored result package is missing. Retry the task."}
                    job.persist()
                self.jobs[session.id] = job
                if job.state == "QUEUED":
                    self.pending.put(session.id)
            except (OSError, ValueError, KeyError, TypeError):
                logger.warning("Skipped invalid local job metadata in %s", metadata_path.parent.name)
        self._cleanup_expired()
        self.worker.start()

    def close(self):
        self.stop.set()
        self.pending.put(None)
        self.worker.join(timeout=2)
        # A process shutdown can interrupt a long model call. Restart marks it ERROR, never COMPLETE.

    def create(self, identifier: UUID | None) -> Job:
        with self.guard:
            if identifier and str(identifier) in self.jobs:
                return self.jobs[str(identifier)]
            # Bound unsubmitted sessions as well as the queue to avoid filling disk accidentally.
            if sum(j.state in {"RECEIVING", "QUEUED", "RUNNING"} for j in self.jobs.values()) >= 32:
                raise HTTPException(429, "Too many active sessions")
            session = Session(self.config.pipeline.session_directory, str(identifier) if identifier else None)
            (session.path / "incoming").mkdir()
            job = Job(session, time.time())
            self.jobs[session.id] = job
            job.persist()
            return job

    def get(self, identifier: UUID) -> Job:
        with self.guard:
            job = self.jobs.get(str(identifier))
            if job is None:
                raise HTTPException(404, "Session not found")
            return job

    def submit(self, job: Job, task: SubmitTask):
        with self.guard:
            if task.page_count > self.config.pipeline.max_pages or sorted(task.page_order) != list(range(1, task.page_count + 1)):
                raise HTTPException(422, "Page order must include pages 1..page_count exactly once")
            if job.state in {"QUEUED", "RUNNING", "COMPLETE"}:
                if job.order != task.page_order:
                    raise HTTPException(409, "An already submitted task cannot change its page order")
                return  # A lost response does not enqueue a duplicate GPU job.
            if job.state == "ERROR":
                raise HTTPException(409, "Create a new session to retry a failed task")
            if set(job.pages) != set(task.page_order):
                raise HTTPException(422, "Upload every requested page before Solve")
            if sum(j.state in {"QUEUED", "RUNNING"} for j in self.jobs.values()) >= self.config.server.max_queued_jobs:
                raise HTTPException(429, "Processing queue is full; retry submission shortly")
            job.order = task.page_order
            job.state = "QUEUED"
            job.session.event("QUEUED")
            job.persist()
            self.pending.put(job.session.id)

    def status(self, job: Job) -> dict:
        with self.guard:
            state = job.state
            if state == "RUNNING":
                try:
                    detail = json.loads((job.session.path / "status.json").read_text(encoding="utf-8"))
                    state = detail["state"]
                    if state == "COMPLETE":
                        state = "SENDING"  # Package must exist before the API exposes a complete job.
                except (OSError, ValueError, KeyError):
                    state = "UNDERSTANDING"
            return {"session_id": job.session.id, "created_at": job.created_at, "state": state,
                    "page_count": len(job.pages), "page_order": job.order,
                    "result_available": job.state == "COMPLETE", "error": job.error,
                    "demo": self.demo}

    def _work(self):
        while not self.stop.is_set():
            identifier = self.pending.get()
            if identifier is None:
                break
            with self.guard:
                job = self.jobs.get(identifier)
                if job is None or job.state != "QUEUED":
                    continue
                job.state = "RUNNING"
                job.persist()
            try:
                paths = [job.session.path / "incoming" / job.pages[i]["file"] for i in job.order]
                result = self.runner(paths, job.session)
                if result["session_id"] != identifier or result["status"] != "complete":
                    raise ValueError("Pipeline returned inconsistent session result")
                result["demo"] = self.demo
                write_json(job.session.path / "result.json", result)
                job.session.event("SENDING")
                build_package(result, job.session.path, job.created_at, demo=self.demo)
                with self.guard:
                    job.state = "COMPLETE"
                    job.persist()
                    job.session.event("COMPLETE")
            except Exception as exc:
                with self.guard:
                    job.state = "ERROR"
                    job.error = {"code": exc.code if isinstance(exc, PipelineError) else "processing_failed",
                                 "message": str(exc)}
                    job.session.event("ERROR", **job.error)
                    job.persist()
                logger.error("Session %s failed: %s", identifier, job.error["code"])
            self._cleanup_expired()

    def delete(self, job: Job):
        with self.guard:
            if job.state in {"RUNNING", "QUEUED"} or job.upload_lock.locked():
                raise HTTPException(409, "Cannot remove a session during upload or processing")
            self._remove(job)

    def _remove(self, job: Job):
        root = self.config.pipeline.session_directory.resolve()
        target = job.session.path.resolve()
        if target.parent != root or target.name != job.session.id:
            raise RuntimeError("Invalid session removal path")
        shutil.rmtree(target)
        self.jobs.pop(job.session.id, None)

    def _cleanup_expired(self):
        if self.config.server.retain_sessions:
            return
        cutoff = time.time() - self.config.server.retention_hours * 3600
        with self.guard:
            for job in list(self.jobs.values()):
                if job.state in {"COMPLETE", "ERROR", "RECEIVING"} and job.created_at < cutoff and not job.upload_lock.locked():
                    self._remove(job)


def demo_runner(config: Config):
    def run(paths, session):
        from .models import Block, Draft
        from .render import CardRenderer, answer_text
        # Deliberately no fake answer to the photographed question.
        draft = Draft(detected_language="en", answered_question_ids=["transport_demo"],
                      final_answer=[], solution=[Block(kind="text", content=(
                          "TRANSPORT DEMO\n\nNo AI solution was generated.\n\n"
                          f"Received {len(paths)} page(s). iPhone, laptop and Watch delivery can be tested."))],
                      numeric_checks=[], warnings=["Transport test only"], confidence=0)
        session.event("RENDERING")
        cards = CardRenderer(config.render, session.path).render(draft, session.path / "cards")
        return {"schema_version": 1, "session_id": session.id, "status": "complete",
                "detected_language": "en", "subject": "mixed", "task_type": "transport_demo",
                "problem_text": "Not read in demo mode", "plain_text_answer": answer_text(draft),
                "solution": [b.model_dump() for b in draft.solution], "final_answer": [],
                "confidence": 0, "warnings": ["TRANSPORT DEMO: not an academic answer"], "cards": cards}
    return run


def create_app(config: Config, *, runner=None, demo: bool = False, advertise: bool | None = None) -> FastAPI:
    manager = JobManager(config, runner or (demo_runner(config) if demo else None), demo=demo)

    @asynccontextmanager
    async def lifespan(app):
        manager.start()
        advertisement = None
        if config.server.advertise if advertise is None else advertise:
            try:
                advertisement = await asyncio.to_thread(Advertisement, config.server)
            except Exception as exc:
                logger.warning("Bonjour unavailable: %s. Manual LAN address remains available.", exc)
        try:
            yield
        finally:
            if advertisement:
                await asyncio.to_thread(advertisement.close)
            manager.close()

    # Swagger assets use CDNs by default; disable them to keep the product entirely offline.
    app = FastAPI(title="Local Offline Vision Solver", version="0.2.0", lifespan=lifespan,
                  docs_url=None, redoc_url=None)
    app.state.jobs = manager

    @app.get("/health")
    def health():
        model_status = "demo" if demo else "unavailable"
        if not demo:
            with LocalModel(config.inference) as model:
                try:
                    model.health()
                    model_status = "ready"
                except InferenceError as exc:
                    model_status = "loading" if "loading" in str(exc) else "unavailable"
        return {"service": "local-vision-solver", "api_version": 1, "status": "ok",
                "model_status": model_status, "demo": demo,
                "max_pages": config.pipeline.max_pages, "max_page_megabytes": config.server.max_page_megabytes}

    @app.post("/v1/sessions", status_code=201)
    def create(body: CreateSession):
        return manager.status(manager.create(body.session_id))

    @app.put("/v1/sessions/{identifier}/pages/{number}")
    async def upload(identifier: UUID, number: int, request: Request):
        if number < 1 or number > config.pipeline.max_pages:
            raise HTTPException(422, "Page number outside supported range")
        job = manager.get(identifier)
        limit = config.server.max_page_megabytes * 1024**2
        try:
            length = int(request.headers.get("content-length", "0"))
        except ValueError:
            raise HTTPException(400, "Invalid content length")
        if length > limit or length < 0:
            raise HTTPException(413, "Page exceeds upload limit")
        async with job.upload_lock:
            if job.state not in {"RECEIVING", "QUEUED", "RUNNING", "COMPLETE"}:
                raise HTTPException(409, "Failed session cannot receive pages")
            temporary = job.session.path / "incoming" / f"upload_{number:02d}.part"
            count = 0
            digest = hashlib.sha256()
            try:
                with temporary.open("wb") as output:
                    async for chunk in request.stream():
                        count += len(chunk)
                        if count > limit:
                            raise HTTPException(413, "Page exceeds upload limit")
                        output.write(chunk)
                        digest.update(chunk)
                if count == 0:
                    raise HTTPException(422, "Empty image")
                with manager.guard:
                    existing = job.pages.get(number)
                    sha = digest.hexdigest()
                    if existing:
                        if existing["sha256"] == sha:
                            return existing  # Safe replay after an upload response was lost.
                        raise HTTPException(409, "Page already uploaded with different content; start a fresh task")
                    if job.state != "RECEIVING":
                        raise HTTPException(409, "Cannot add pages after Solve")
                    total = sum(page["bytes"] for page in job.pages.values()) + count
                    if total > config.pipeline.max_input_megabytes * 1024**2:
                        raise HTTPException(413, "Session exceeds total input limit")
                    try:
                        with Image.open(temporary) as image:
                            format_name = image.format
                            if format_name not in {"JPEG", "PNG"} or getattr(image, "n_frames", 1) != 1:
                                raise ValueError("Only single-frame JPEG/PNG are supported by the LAN API")
                            if min(image.size) < 160:
                                raise ValueError("Image resolution is too low")
                            image.verify()
                    except (OSError, ValueError, Image.DecompressionBombError) as exc:
                        raise HTTPException(422, str(exc)) from exc
                    filename = f"page_{number:02d}.{'jpg' if format_name == 'JPEG' else 'png'}"
                    temporary.replace(job.session.path / "incoming" / filename)
                    page = {"number": number, "file": filename, "bytes": count, "sha256": sha}
                    job.pages[number] = page
                    job.persist()
                    return page
            finally:
                temporary.unlink(missing_ok=True)

    @app.post("/v1/sessions/{identifier}/solve", status_code=202)
    async def solve(identifier: UUID, task: SubmitTask):
        job = manager.get(identifier)
        async with job.upload_lock:
            manager.submit(job, task)
        return manager.status(job)

    @app.get("/v1/sessions/{identifier}")
    def status(identifier: UUID):
        return manager.status(manager.get(identifier))

    def completed(identifier: UUID) -> Job:
        job = manager.get(identifier)
        if job.state != "COMPLETE":
            raise HTTPException(425, "Result is not ready")
        return job

    @app.get("/v1/sessions/{identifier}/result")
    def result(identifier: UUID):
        job = completed(identifier)
        return json.loads((job.session.path / "result.json").read_text(encoding="utf-8"))

    @app.get("/v1/sessions/{identifier}/package")
    def package(identifier: UUID):
        job = completed(identifier)
        return FileResponse(job.session.path / "result.lvsp", media_type="application/octet-stream",
                            filename=f"{identifier}.lvsp", headers={"Cache-Control": "no-store"})

    @app.get("/v1/sessions/{identifier}/cards/{index}")
    def card(identifier: UUID, index: int):
        job = completed(identifier)
        value = json.loads((job.session.path / "result.json").read_text(encoding="utf-8"))
        cards = value["cards"]
        if index < 1 or index > len(cards):
            raise HTTPException(404, "Card not found")
        return FileResponse(job.session.path / "cards" / cards[index-1]["file"], media_type="image/png")

    @app.delete("/v1/sessions/{identifier}", status_code=204)
    def delete(identifier: UUID):
        manager.delete(manager.get(identifier))

    return app

