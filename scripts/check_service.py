"""One owned demo process lifecycle for source and frozen acceptance checks."""
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time
import httpx

ROOT=Path(__file__).resolve().parents[1]


class DemoService:
    def __init__(self,run,executable=None):
        self.run=run
        self.secret=secrets.token_urlsafe(32)
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0));self.port=sock.getsockname()[1]
        self.base=f'http://127.0.0.1:{self.port}'
        self.headers={'Authorization':'Bearer '+self.secret}
        config=run/'config.toml'
        config.write_text('[pipeline]\nsession_directory = "sessions"\n[server]\n'+f'host="127.0.0.1"\nport={self.port}\nadvertise=false\n',encoding='utf-8')
        backend=[str(executable.resolve())] if executable else [sys.executable,'-m','local_vision_solver']
        self.command=[*backend,'--config',str(config),'serve','--demo','--no-discovery','--admin-stdin']
        self.process=None;self.log=None

    def start(self):
        self.log=(self.run/'server.log').open('w',encoding='utf-8')
        self.process=subprocess.Popen(self.command,cwd=ROOT,stdin=subprocess.PIPE,stdout=self.log,stderr=subprocess.STDOUT,
            env=dict(os.environ,PYTHONUTF8='1',PYTHONIOENCODING='utf-8'),creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        self.process.stdin.write((json.dumps({'secret':self.secret})+'\n').encode());self.process.stdin.close()
        try:
            with httpx.Client(trust_env=False,timeout=1) as client:
                deadline=time.monotonic()+30
                while time.monotonic()<deadline:
                    if self.process.poll() is not None:raise RuntimeError('Backend exited; see '+str(self.run/'server.log'))
                    try:
                        if client.get(self.base+'/ready').status_code==200:return self
                    except httpx.HTTPError:pass
                    time.sleep(.1)
            raise RuntimeError('Startup timeout; see '+str(self.run/'server.log'))
        except BaseException:self.close();raise

    def pairing(self):
        with httpx.Client(base_url=self.base,headers=self.headers,trust_env=False,timeout=5) as client:
            response=client.post('/v1/admin/pairing');response.raise_for_status()
            return response.json()['token']

    def close(self):
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:self.process.kill();self.process.wait(timeout=5)
        if self.log:self.log.close()

    def __enter__(self):return self.start()
    def __exit__(self,*args):self.close()
