"""Shared CLI/API finalization. COMPLETE is published only after inspection."""
import hashlib
import json
from pathlib import Path
import shutil
from uuid import uuid4
from .models import VerifiedAnswer
from .package import build_package, inspect_package
from .render import CardRenderer, answer_text
from .storage import write_json, write_bytes


def file_hash(path: Path):
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def save_answer(session, answer: VerifiedAnswer):
    if session.id != answer.session_id:
        raise ValueError("Verified answer belongs to a different session")
    write_json(session.path / "verified_answer.json", answer.model_dump(mode="json"))
    write_bytes(session.path / "answer.txt", answer_text(answer.draft).encode("utf-8"))
    return file_hash(session.path / "verified_answer.json")


def load_answer(session, expected_hash=None):
    path = session.path / "verified_answer.json"
    if expected_hash and file_hash(path) != expected_hash:
        raise ValueError("verified_answer_integrity")
    value = VerifiedAnswer.model_validate_json(path.read_text(encoding="utf-8"))
    if value.session_id != session.id:
        raise ValueError("verified_answer_session_mismatch")
    if (session.path / "answer.txt").read_text(encoding="utf-8") != answer_text(value.draft):
        raise ValueError("verified_text_integrity")
    return value


def finalize_outputs(config, session, answer: VerifiedAnswer, created_at, transition=lambda state: None):
    transition("RENDERING")
    staging = session.path / ("cards-" + uuid4().hex)
    try:
        cards = CardRenderer(config.render, session.path).render(answer.draft, staging)
        destination = session.path / "cards"
        if destination.exists():
            if destination.resolve().parent != session.path.resolve():
                raise ValueError("Invalid cards path")
            shutil.rmtree(destination)
        staging.replace(destination)
        result = dict(answer.metadata, schema_version=1, session_id=session.id, status="complete",
                      detected_language=answer.draft.detected_language,
                      solution=[b.model_dump() for b in answer.draft.solution],
                      final_answer=[b.model_dump() for b in answer.draft.final_answer],
                      plain_text_answer=answer_text(answer.draft), confidence=answer.draft.confidence,
                      cards=cards, demo=answer.demo)
        write_json(session.path / "result.json", result)
        transition("PACKAGING")
        build_package(result, session.path, created_at, demo=answer.demo)
        validate_outputs(session)
        return result
    finally:
        if staging.exists() and staging.resolve().parent == session.path.resolve():
            shutil.rmtree(staging)


def validate_outputs(session, result_sha256=None, package_sha256=None):
    if result_sha256 and file_hash(session.path / "result.json") != result_sha256:
        raise ValueError("result_integrity")
    if package_sha256 and file_hash(session.path / "result.zip") != package_sha256:
        raise ValueError("package_integrity")
    result = json.loads((session.path / "result.json").read_text(encoding="utf-8"))
    import zipfile
    with zipfile.ZipFile(session.path/'result.zip') as archive:
        if json.loads(archive.read('result.json'))!=result:
            raise ValueError('structured_result_integrity')
    header = inspect_package(session.path / "result.zip")
    if result["session_id"] != session.id or header["session_id"] != session.id:
        raise ValueError("result_session_mismatch")
    if (session.path / "answer.txt").read_text(encoding="utf-8") != result["plain_text_answer"]:
        raise ValueError("text_integrity")
    for card in header["cards"]:
        if file_hash(session.path / "cards" / card["file"]) != card["sha256"]:
            raise ValueError("card_integrity")
    return result
