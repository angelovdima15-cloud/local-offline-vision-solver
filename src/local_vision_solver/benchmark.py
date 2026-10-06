from pathlib import Path
import json
import statistics
import unicodedata

from .config import Config
from .pipeline import Pipeline, PipelineError
from .storage import write_json


def normalize(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def run_benchmark(config: Config, manifest_path: Path, output: Path, label: str, repeats: int = 1) -> dict:
    if output.exists():
        raise ValueError("Benchmark output exists; use a new path to retain prior results")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    cases = manifest["cases"]
    if not cases:
        raise ValueError("Benchmark needs real task photographs with expert reference answers")
    output.parent.mkdir(parents=True, exist_ok=True)
    records = []
    for repeat in range(repeats):
        for case in cases:
            paths = [(manifest_path.parent / p).resolve() for p in case["images"]]
            # Catch bad fixture paths as input errors, not evidence of model failure.
            if not paths or any(not p.is_file() for p in paths):
                raise ValueError(f"Case {case['id']}: reference images missing")
            print(f"Benchmark {case['id']}, repetition {repeat + 1}", flush=True)
            try:
                session, result = Pipeline(config).solve(paths)
                final = normalize(result["plain_text_answer"])
                required = case.get("expected_fragments", [])
                fragments_pass = all(normalize(fragment) in final for fragment in required)
                metadata_pass = (result["detected_language"] == case["language"]
                                 and result["subject"] == case["subject"])
                record = {"case_id": case["id"], "repetition": repeat + 1, "session_id": session.id,
                          "status": "complete", "seconds": result["metrics"]["total_seconds"],
                          "gpu_peak_used_megabytes": result["metrics"]["resources"]["gpu_peak_used_megabytes"],
                          "reference_fragments_pass": fragments_pass if required else None,
                          "metadata_pass": metadata_pass, "human_correctness_score": None,
                          "human_notes": "Review full reading, all calculations and rendered cards against source.",
                          "session_path": str(session.path), "metrics": result["metrics"]}
            except PipelineError as exc:
                record = {"case_id": case["id"], "repetition": repeat + 1, "session_id": exc.session.id,
                          "status": "error", "code": exc.code, "error": str(exc),
                          "human_correctness_score": 0, "session_path": str(exc.session.path)}
            records.append(record)
            write_json(output, {"label": label, "runtime": config.runtime.model_dump(mode="json"),
                                "records": records, "status": "running"})
    elapsed = [r["seconds"] for r in records if r["status"] == "complete"]
    report = {"label": label, "runtime": config.runtime.model_dump(mode="json"),
              "manifest": str(manifest_path.resolve()), "records": records, "status": "complete",
              "summary": {"total_runs": len(records), "completed_runs": len(elapsed),
                          "failed_runs": len(records) - len(elapsed),
                          "median_seconds": statistics.median(elapsed) if elapsed else None,
                          "max_seconds": max(elapsed) if elapsed else None,
                          "under_target": sum(s <= config.pipeline.latency_target_seconds for s in elapsed)},
              "selection": "Pending expert correctness review. Fragment matches are not accuracy evidence."}
    write_json(output, report)
    return report

