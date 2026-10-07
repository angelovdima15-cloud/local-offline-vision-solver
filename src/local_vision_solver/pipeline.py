from pathlib import Path
import json
import time

from . import prompts
from .checks import check_equalities
from .config import Config
from .images import ImageInputError, Page, prepare_page, retry_views
from .inference import LocalModel
from .locking import inference_lock
from .models import Audit, Draft, Reading, VerifiedAnswer
from .image_policy import DECODE_LOCK, ImagePolicy, check_prepared
from .render import CardRenderer, answer_text
from .resources import ResourceMonitor
from .storage import Session, write_json


class PipelineError(RuntimeError):
    def __init__(self, message: str, session: Session, code: str = "processing_failed"):
        super().__init__(message)
        self.session = session
        self.code = code


def serialize(value) -> str:
    return json.dumps(value.model_dump() if hasattr(value, "model_dump") else value, ensure_ascii=False)


def validate_reading(reading: Reading, page_count: int) -> None:
    if sorted(reading.page_order) != list(range(1, page_count + 1)):
        raise ValueError("Reconstructed page order must include every original exactly once")
    ids = [q.id for q in reading.questions]
    if len(set(ids)) != len(ids):
        raise ValueError("Question ids must be unique")
    for question in reading.questions:
        if any(p < 1 or p > page_count for p in question.page_numbers):
            raise ValueError("Question references an absent original page")
    for uncertainty in reading.uncertainties:
        if uncertainty.page_number > page_count:
            raise ValueError("Uncertainty references an absent original page")


def draft_issues(draft: Draft, reading: Reading) -> list[str]:
    issues = []
    expected = {q.id for q in reading.questions}
    actual = set(draft.answered_question_ids)
    if expected != actual or len(actual) != len(draft.answered_question_ids):
        issues.append(f"Question coverage mismatch: expected {sorted(expected)}, got {draft.answered_question_ids}")
    if draft.detected_language != reading.detected_language:
        issues.append("Declared answer language differs from primary instructional language")
    if not draft.numeric_checks:
        if draft.numeric_checks_applicability!='not_applicable' or not draft.numeric_checks_reason.strip():
            issues.append('Empty numeric checks require explicit not_applicable and an explanation; otherwise checks are missing')
    elif draft.numeric_checks_applicability=='not_applicable':
        issues.append('Numeric checks contradict not_applicable')
    return issues


def audit_accepted(audit: Audit) -> bool:
    return (audit.verdict == "accept" and not audit.issues and audit.question_understanding_checked
            and audit.all_questions_answered and audit.units_checked and audit.answer_options_checked
            and audit.original_images_checked)


class Pipeline:
    def __init__(self, config: Config):
        self.config = config

    def solve(self, paths: list[Path], *, session: Session | None = None) -> tuple[Session, dict]:
        from .job_service import save_answer, finalize_outputs
        session, answer = self.verify(paths, session=session)
        save_answer(session, answer)
        session.event("ANSWER_READY")
        result = finalize_outputs(self.config, session, answer, time.time(), session.event)
        session.event("COMPLETE")
        return session, result

    def verify(self, paths: list[Path], *, session: Session | None = None) -> tuple[Session, VerifiedAnswer]:
        # Never keep model messages, reading or drafts in instance state across sessions.
        session = session or Session(self.config.pipeline.session_directory)
        started = time.perf_counter()
        with ResourceMonitor() as resources:
            try:
                if not paths or len(paths) > self.config.pipeline.max_pages:
                    raise ValueError(f"Provide 1–{self.config.pipeline.max_pages} ordered images")
                for path in paths:
                    if not path.is_file():
                        raise ImageInputError(f"Image file not found: {path}")
                if sum(p.stat().st_size for p in paths) > self.config.pipeline.max_input_megabytes * 1024**2:
                    raise ImageInputError("Images exceed configured total input limit")
                session.event("VALIDATING_IMAGES", page_count=len(paths))
                pages = []
                for index, path in enumerate(paths, 1):
                    with DECODE_LOCK:
                        ImagePolicy(self.config.server.max_image_pixels).inspect(path)
                        pages.append(prepare_page(path, index, session.path))
                    check_prepared(session.path, self.config.pipeline.max_prepared_megabytes * 1024**2)
                write_json(session.path / "image_quality.json", [p.summary() for p in pages])
                original_views = [(f"ORIGINAL PAGE {p.number} of {len(pages)}", p.oriented) for p in pages]
                with inference_lock(self.config.inference.endpoint), LocalModel(self.config.inference, session) as model:
                    model.begin_session()
                    reading = self._read(model, session, pages, original_views)
                    for recovery in range(self.config.pipeline.max_reading_retries + 1):
                        solved = self._solve_and_verify(model, session, reading, original_views)
                        if not isinstance(solved, Audit):
                            draft, independent, audit, arithmetic = solved
                            break
                        if recovery >= self.config.pipeline.max_reading_retries:
                            raise PipelineError("Task interpretation remains uncertain after automatic recovery. "
                                                "Check original pages and retake unreadable/missing areas.",
                                                session, "retake_required")
                        reading = self._read(model, session, pages, original_views,
                            feedback="Independent audit found source interpretation issues:\n" + serialize(solved),
                                             force_retry=True)
                    model.clear_context()
                    model.context_owned = False
                    session.event("VERIFYING", context_cleared=True)
                    elapsed = time.perf_counter() - started
                    warnings = list(dict.fromkeys(reading.warnings + draft.warnings))
                    if elapsed > self.config.pipeline.latency_target_seconds:
                        warnings.append("latency_target_exceeded; all verification stages were retained")
                    result = {"schema_version": 1, "session_id": session.id, "status": "complete",
                              "detected_language": reading.detected_language, "subject": reading.subject,
                              "task_type": reading.task_type, "number_of_questions": len(reading.questions),
                              "problem_text": reading.problem_text, "page_order": reading.page_order,
                              "solution": [b.model_dump() for b in draft.solution],
                              "final_answer": [b.model_dump() for b in draft.final_answer],
                              "plain_text_answer": answer_text(draft), "confidence": draft.confidence,
                              "confidence_note": "Subjective model estimate; not calibrated or a guarantee.",
                              "verification": {"audit": audit.model_dump(), "numeric_checks": arithmetic,
                                               "independent_pass_completed": True},
                              "render_mode": self.config.render.math_engine,
                              "warnings": warnings,
                              "metrics": {"total_seconds": round(elapsed, 3), "inference": model.metrics,
                                          "resources": resources.summary()},
                              "runtime": self.config.runtime.model_dump(mode="json")}
                    return session, VerifiedAnswer(session_id=session.id, draft=draft, metadata=result)
            except Exception as exc:
                error = exc if isinstance(exc, PipelineError) else PipelineError(str(exc), session)
                session.event("ERROR", code=error.code, message=str(error),
                              seconds=round(time.perf_counter() - started, 3), resources=resources.summary())
                raise error from (None if error is exc else exc)

    def _read(self, model: LocalModel, session: Session, pages: list[Page],
              originals: list[tuple[str, Path]], feedback: str = "", force_retry: bool = False) -> Reading:
        session.event("UNDERSTANDING")
        hints = [{"page": p.number, "warnings": p.warnings} for p in pages]
        variants = [(f"Contrast variant of ORIGINAL PAGE {p.number}; not an additional page", p.enhanced)
                    for p in pages if p.enhanced]
        reading = model.generate("UNDERSTANDING", prompts.READ + "\nQuality hints: " + serialize(hints)
                                 + "\n" + feedback, Reading, originals + variants)
        validate_reading(reading, len(pages))
        write_json(session.path / "reading_initial.json", reading.model_dump())
        if force_retry or reading.uncertainties or not reading.sufficient_information:
            for attempt in range(self.config.pipeline.max_reading_retries):
                session.event("UNDERSTANDING", recovery_attempt=attempt + 1)
                with DECODE_LOCK:
                    crops = retry_views(pages, reading.uncertainties, session.path)
                check_prepared(session.path, self.config.pipeline.max_prepared_megabytes * 1024**2)
                instruction = (prompts.READ + "\nRe-read from ORIGINALS and their detail crops. "
                               "Compare alternatives; only resolve ambiguities supported by pixels. "
                               "Previous interpretation:\n" + serialize(reading) + "\n" + feedback)
                reading = model.generate("UNDERSTANDING_RETRY", instruction, Reading, originals + variants + crops)
                validate_reading(reading, len(pages))
                if not reading.uncertainties and reading.sufficient_information:
                    break
        write_json(session.path / "reading.json", reading.model_dump())
        if reading.uncertainties or not reading.sufficient_information:
            raise PipelineError("Source remains unreadable or required content is missing after local recovery. "
                                "Retake the affected area or add the missing page.", session, "retake_required")
        return reading

    def _solve_and_verify(self, model: LocalModel, session: Session, reading: Reading,
                          originals: list[tuple[str, Path]]) -> tuple | Audit:
        source = "\nReconstructed task:\n" + serialize(reading)
        session.event("SOLVING")
        candidate = model.generate("SOLVING", prompts.SOLVE + source, Draft, originals, seed=17)
        session.event("VERIFYING")
        # The independent model request contains no candidate solution.
        independent = model.generate("VERIFYING_INDEPENDENT", prompts.INDEPENDENT + source,
                                     Draft, originals, seed=43)
        write_json(session.path / "independent_solution.json", independent.model_dump())
        for attempt in range(self.config.pipeline.max_corrections + 1):
            arithmetic = check_equalities(candidate.numeric_checks)
            issues = draft_issues(candidate, reading)
            independent_issues = draft_issues(independent, reading)
            renderer = CardRenderer(self.config.render, session.path)
            for value, target in ((candidate, issues), (independent, independent_issues)):
                for block in value.final_answer + value.solution:
                    if block.kind == "math":
                        try:
                            renderer.math_image(block.content)
                        except RuntimeError as exc:
                            target.append(str(exc))
            write_json(session.path / f"independent_solution_{attempt:02d}.json", independent.model_dump())
            independent_arithmetic = check_equalities(independent.numeric_checks)
            audit_prompt = (prompts.AUDIT + source + "\nCandidate:\n" + serialize(candidate)
                            + "\nIndependent solution:\n" + serialize(independent)
                            + "\nLocal candidate coverage checks:\n" + serialize(issues)
                            + "\nLocal candidate numeric checks:\n" + serialize(arithmetic)
                            + "\nLocal independent coverage checks:\n" + serialize(independent_issues)
                            + "\nLocal independent numeric checks:\n" + serialize(independent_arithmetic))
            audit = model.generate("VERIFYING_AUDIT", audit_prompt, Audit, originals, seed=71)
            write_json(session.path / f"candidate_{attempt:02d}.json", candidate.model_dump())
            write_json(session.path / f"audit_{attempt:02d}.json", audit.model_dump())
            write_json(session.path / f"numeric_checks_{attempt:02d}.json", arithmetic)
            if audit.verdict == "unreadable":
                raise PipelineError("Verifier found required information absent from the photos. "
                                    "Add missing pages or retake affected areas.", session, "retake_required")
            if audit.verdict == "reread":
                return audit
            if (audit_accepted(audit) and not issues and not independent_issues
                    and all(c["passed"] for c in arithmetic)
                    and all(c["passed"] for c in independent_arithmetic)):
                return candidate, independent, audit, arithmetic
            if attempt >= self.config.pipeline.max_corrections:
                raise PipelineError("Verification did not establish a complete consistent answer. "
                                    "No unverified cards were released. Inspect local audit files.",
                                    session, "verification_failed")
            session.event("CORRECTING", correction_attempt=attempt + 1)
            candidate = model.generate("CORRECTING", prompts.SOLVE + source
                                       + "\nRevise candidate using originals; resolve ALL issues.\n"
                                       + audit_prompt + "\nAudit:\n" + serialize(audit),
                                       Draft, originals, seed=29)
            # Re-run independent solution after correction if its own structural/numeric checks failed.
            if independent_issues or any(not c["passed"] for c in independent_arithmetic):
                independent = model.generate("VERIFYING_INDEPENDENT", prompts.INDEPENDENT + source,
                                             Draft, originals, seed=53)
            session.event("VERIFYING")
        raise RuntimeError("Verification loop completed without a verdict")
