"""Real authenticated HTTP demo through source or frozen backend."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import subprocess
import sys
from uuid import uuid4
from check_service import DemoService,ROOT


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--executable',type=Path)
    args=parser.parse_args()
    run=ROOT/'.cache/acceptance-http'/(datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid4().hex[:6]);run.mkdir(parents=True)
    with DemoService(run,args.executable) as service:
        result=subprocess.run([sys.executable,'scripts/smoke_api.py','--url',service.base,'--output',str(run),'--admin-stdin'],cwd=ROOT,
            input=json.dumps({'secret':service.secret}),capture_output=True,text=True,encoding='utf-8')
        if result.returncode:
            print(result.stdout+result.stderr);return result.returncode
        report=json.loads((run/'report.json').read_text(encoding='utf-8'))
        print(f"real HTTP: PASS; pages={report['pages_uploaded']}; checksum={report['checksum_verified']}; demo=True; report={run/'report.json'}")
    return 0


if __name__=='__main__':raise SystemExit(main())
