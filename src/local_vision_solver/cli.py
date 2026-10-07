import argparse
from contextlib import ExitStack
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
    parser.add_argument("--data-dir",type=Path)
    parser.add_argument("--api-port",type=int)
    parser.add_argument("--inference-port",type=int)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor", help="Inspect GPU, files, fonts and local inference health")
    sub.add_parser("start-model", help="Run local llama.cpp in the foreground")
    serve = sub.add_parser("serve", help="Start the LAN service and local model")
    serve.add_argument("--demo", action="store_true", help="Clearly marked transport demo; does not solve images")
    serve.add_argument("--external-model", action="store_true", help="Use an already running loopback model")
    serve.add_argument("--no-discovery", action="store_true", help="Disable Bonjour for local tests")
    serve.add_argument("--open-browser", action="store_true", help="Open the local website on this laptop")
    serve.add_argument("--admin-stdin",action="store_true",help="Read private desktop credential from stdin")
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
        config = load_config(args.config,args.data_dir)
        if args.api_port is not None:
            config.server.port=args.api_port
        if args.inference_port is not None:
            config.inference.endpoint=f'http://127.0.0.1:{args.inference_port}'
        config = type(config).model_validate(config.model_dump())
        from .logging_setup import configure_logging
        configure_logging(config.paths.logs,'backend')
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
            from .process_supervisor import ProcessSupervisor,ModelMonitor
            secret=None
            if args.admin_stdin:
                secret=json.loads(sys.stdin.readline())['secret']
                if not isinstance(secret,str) or len(secret)<32:
                    raise ValueError('Invalid private admin credential')
            with ExitStack() as stack:
                from .locking import file_lock
                stack.enter_context(file_lock(config.paths.data/".backend.lock"))
                from .runtime_lock import runtime_process_lock
                if not args.demo and not args.external_model:stack.enter_context(runtime_process_lock(config.inference.endpoint))
                supervisor=ProcessSupervisor()
                process = None
                try:
                    if not args.demo and not args.external_model:
                        process = launch_server(config,supervisor=supervisor)
                        supervisor.wait_ready(process,config.inference.endpoint)
                    app = create_app(config, demo=args.demo,
                                     advertise=False if args.no_discovery else None, open_browser=args.open_browser,admin_secret=secret)
                    if process:
                        monitor=ModelMonitor(config,supervisor,process,app.state.jobs)
                        monitor.thread.start()
                    uvicorn.run(app, host=config.server.host, port=config.server.port, log_level="info",access_log=False)
                finally:
                    supervisor.close()
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
