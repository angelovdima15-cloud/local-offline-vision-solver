import argparse
import json
from pathlib import Path
import sys

from .benchmark import run_benchmark
from .config import load_config
from .models import Draft
from .pipeline import Pipeline, PipelineError
from .render import CardRenderer
from .runtime import inspect_environment, start_server
from .storage import write_json


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Local Offline Vision Solver: CLI and LAN MVP")
    parser.add_argument("--config", type=Path, default=Path("config.toml"))
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor", help="Inspect GPU, files, fonts and local inference health")
    sub.add_parser("start-model", help="Run local llama.cpp in the foreground")
    serve = sub.add_parser("serve", help="Start the LAN service and local model")
    serve.add_argument("--demo", action="store_true", help="Clearly marked transport demo; does not solve images")
    serve.add_argument("--external-model", action="store_true", help="Use an already running loopback model")
    serve.add_argument("--no-discovery", action="store_true", help="Disable Bonjour for local tests")
    solve = sub.add_parser("solve", help="Solve one fresh session; images are in upload order")
    solve.add_argument("images", type=Path, nargs="+")
    render = sub.add_parser("render", help="Render an existing validated answer without a model")
    render.add_argument("answer", type=Path)
    render.add_argument("--output", type=Path, required=True)
    benchmark = sub.add_parser("benchmark", help="Run reference images through the complete pipeline")
    benchmark.add_argument("manifest", type=Path)
    benchmark.add_argument("--label", required=True)
    benchmark.add_argument("--output", type=Path, required=True)
    benchmark.add_argument("--repeats", type=int, default=1)
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config)
        if args.command == "doctor":
            report = inspect_environment(config)
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 0 if report["ready"] else 1
        if args.command == "start-model":
            return start_server(config)
        if args.command == "serve":
            import uvicorn
            from .runtime import launch_server, stop_server
            from .server import create_app
            process = None
            try:
                if not args.demo and not args.external_model:
                    process = launch_server(config)
                app = create_app(config, demo=args.demo,
                                 advertise=False if args.no_discovery else None)
                uvicorn.run(app, host=config.server.host, port=config.server.port, log_level="info")
            finally:
                if process:
                    stop_server(process)
            return 0
        if args.command == "solve":
            session, result = Pipeline(config).solve(args.images)
            print(json.dumps({"session_id": session.id, "result": str(session.path / "result.json"),
                              "cards": str(session.path / "cards"),
                              "seconds": result["metrics"]["total_seconds"]}, ensure_ascii=False, indent=2))
        if args.command == "render":
            draft = Draft.model_validate_json(args.answer.read_text(encoding="utf-8"))
            args.output.parent.mkdir(parents=True, exist_ok=True)
            manifest = CardRenderer(config.render, args.output.parent).render(draft, args.output)
            write_json(args.output / "manifest.json", manifest)
            print(f"Rendered {len(manifest)} cards: {args.output.resolve()}")
        if args.command == "benchmark":
            if args.repeats < 1:
                parser.error("--repeats must be >= 1")
            report = run_benchmark(config, args.manifest, args.output, args.label, args.repeats)
            print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
        return 0
    except PipelineError as exc:
        print(json.dumps({"error": exc.code, "message": str(exc), "session": str(exc.session.path)},
                         ensure_ascii=False), file=sys.stderr)
        return 2
    except (ValueError, RuntimeError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
