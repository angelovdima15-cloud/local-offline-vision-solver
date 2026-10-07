"""Elevated helper accepts only the app's sibling backend and product API ports."""
import argparse
from pathlib import Path
import subprocess
import sys


def command(port,program):
    if not 8765<=port<=8775 or program.name!='VisionBackend.exe' or not program.is_file():
        raise ValueError('Invalid firewall scope')
    return ['netsh.exe','advfirewall','firewall','add','rule',f'name=VisionSolver-{port}',
            'dir=in','action=allow',f'program={program.resolve()}', 'enable=yes','profile=private',
            f'localport={port}','protocol=TCP','remoteip=LocalSubnet']


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',required=True,type=int)
    args=parser.parse_args()
    program=Path(sys.executable).resolve().parent/'VisionBackend.exe'
    result=subprocess.run(command(args.port,program),creationflags=subprocess.CREATE_NO_WINDOW,capture_output=True)
    return result.returncode


if __name__=='__main__':raise SystemExit(main())
