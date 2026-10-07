"""Headless source/frozen QML smoke; hardware setup is a separate acceptance."""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--executable',type=Path)
    parser.add_argument('--demo',action='store_true')
    args=parser.parse_args()
    run=ROOT/'.cache/desktop-checks'/(datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid4().hex[:6])
    run.mkdir(parents=True)
    command=[str(args.executable.resolve())] if args.executable else [sys.executable,'-m','local_vision_solver.desktop.main']
    command+=['--data-dir',str(run/'данные с пробелами'),'--smoke',str(run/'desktop.png')]
    if args.demo:command+=['--demo']
    with (run/'check.log').open('w',encoding='utf-8') as log:
        process=subprocess.run(command,cwd=run,stdout=log,stderr=subprocess.STDOUT,timeout=45,
            env=dict(os.environ,PYTHONUTF8='1',PYTHONIOENCODING='utf-8'),creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    messages=(run/'check.log').read_text(encoding='utf-8',errors='replace')
    for qt_log in (run/'данные с пробелами'/'logs').glob('app.log*'):
        messages+=qt_log.read_text(encoding='utf-8',errors='replace')
    failures=any(s in messages for s in ('ReferenceError:','TypeError:','failed to load component','is not a type','Unable to assign'))
    passed=process.returncode==0 and (run/'desktop.png').is_file() and not failures
    (run/'report.json').write_text(json.dumps({'passed':passed,'exit':process.returncode,'demo':args.demo,'hardware_acceptance':False},indent=2),encoding='utf-8')
    print(f"desktop smoke: {'PASS' if passed else 'FAIL'}; exit={process.returncode}; log={run/'check.log'}")
    if not passed:print(messages[-5000:])
    return 0 if passed else 1


if __name__=='__main__':raise SystemExit(main())
