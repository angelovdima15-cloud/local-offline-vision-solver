"""Small offline source-navigation and compact test-output commands for development."""
from __future__ import annotations

import argparse
import ast
from datetime import datetime
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]


def source_path(value: str) -> Path:
    path = (ROOT / value).resolve()
    if not path.is_relative_to(ROOT) or not path.is_file():
        raise ValueError("Expected an existing file inside the project")
    return path


def outline(value: str) -> int:
    path = source_path(value)
    tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    label = path.relative_to(ROOT).as_posix()

    def visit(node: ast.AST, parents: tuple[str, ...] = ()) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                qualified = (*parents, child.name)
                kind = "class" if isinstance(child, ast.ClassDef) else "async def" if isinstance(child, ast.AsyncFunctionDef) else "def"
                print(f"{label}:{child.lineno}-{child.end_lineno} {kind} {'.'.join(qualified)}")
                visit(child, qualified)
            else:
                visit(child, parents)

    visit(tree)
    return 0


def read(value: str, start: int, end: int) -> int:
    if start < 1 or end < start:
        raise ValueError("Line range must satisfy 1 <= start <= end")
    lines = source_path(value).read_text(encoding="utf-8-sig").splitlines()
    for index in range(start - 1, min(end, len(lines))):
        print(f"{index + 1}: {lines[index]}")
    return 0


def check(targets: list[str]) -> int:
    selected = targets or ["tests"]
    log_dir = ROOT / ".cache" / "dev-checks"
    log_dir.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
    log_path = log_dir / f"{run_id}.log"
    temporary_root = (log_dir / f"{run_id}-tmp").resolve()
    if not temporary_root.is_relative_to(ROOT.resolve()) or temporary_root.exists():
        raise ValueError("Expected a fresh temporary directory inside the project")
    command = [sys.executable, "-m", "pytest", "-q", "--tb=short", "--basetemp", str(temporary_root), *selected]
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    started = time.perf_counter()
    with log_path.open("w", encoding="utf-8", newline="\n") as log:
        log.write(f"Command: {subprocess.list2cmdline(command)}\n")
        log.flush()
        result = subprocess.run(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT, check=False)
    lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    print(f"pytest targets: {' '.join(selected)}")
    print(f"exit={result.returncode}; seconds={time.perf_counter() - started:.2f}; full log: {log_path.relative_to(ROOT)}")
    if result.returncode:
        print("\n".join(lines[-80:]))
    else:
        summary = [line for line in lines if re.search(r"\b\d+ (passed|failed|skipped|error|xfailed|xpassed)", line)]
        print("\n".join(summary[-3:] or lines[-3:]))
    return result.returncode


def main() -> int:
    # Native tools consume UTF-8 when stdout is redirected from Windows Python.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
        sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    symbols = sub.add_parser("outline", help="Print Python symbol names and source ranges")
    symbols.add_argument("file")
    excerpt = sub.add_parser("read", help="Read numbered lines of a project file")
    excerpt.add_argument("file")
    excerpt.add_argument("start", type=int)
    excerpt.add_argument("end", type=int)
    tests = sub.add_parser("check", help="Run selected pytest targets; retain full output")
    tests.add_argument("targets", nargs="*")
    args = parser.parse_args()
    try:
        if args.command == "outline":
            return outline(args.file)
        if args.command == "read":
            return read(args.file, args.start, args.end)
        return check(args.targets)
    except (OSError, ValueError, SyntaxError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
