from datetime import datetime, timezone
from pathlib import Path
import json
import os
import uuid
import time
import logging


def write_json(path: Path, value: object) -> None:
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    with temporary.open('w',encoding='utf-8') as handle:
        handle.write(json.dumps(value,ensure_ascii=False,indent=2))
        handle.flush()
        os.fsync(handle.fileno())
    try:
        # Windows readers may briefly hold a handle without FILE_SHARE_DELETE.
        for attempt in range(20):
            try:
                os.replace(temporary, path)
                return
            except PermissionError:
                if os.name != "nt" or attempt == 19:
                    raise
                time.sleep(.02)
    finally:
        temporary.unlink(missing_ok=True)


class Session:
    def __init__(self, root: Path, session_id: str | None = None, *, restore: bool = False):
        self.id = str(uuid.UUID(session_id)) if session_id else str(uuid.uuid4())
        self.path = root / self.id
        if restore:
            if not self.path.is_dir():
                raise FileNotFoundError(self.path)
            return
        self.path.mkdir(parents=True, exist_ok=False)
        (self.path / "originals").mkdir()
        (self.path / "processed").mkdir()
        self.event("RECEIVING")

    def event(self, state: str, **details: object) -> None:
        callback=getattr(self,'on_stage',None)
        if callback:callback(state)
        value = {"session_id": self.id, "timestamp": datetime.now(timezone.utc).isoformat(),
                 "state": state, **details}
        try:
            write_json(self.path / "status.json", value)
            with (self.path / "events.jsonl").open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(value, ensure_ascii=False) + "\n")
        except OSError:
            logging.getLogger("vision.service").error("Event log failed for %s", self.id, exc_info=True)


def write_bytes(path: Path, data: bytes):
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temporary.open("wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
