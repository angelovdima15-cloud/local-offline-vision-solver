import socket
import subprocess
import sys
import pytest
from local_vision_solver.process_supervisor import ProcessSupervisor,choose_port


def test_occupied_port_skipped():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        if port==65535:pytest.skip('No adjacent port')
        assert choose_port('127.0.0.1',port,port+1)==port+1


def test_supervisor_stops_only_owned_child():
    flags=subprocess.CREATE_NO_WINDOW if sys.platform=='win32' else 0
    other=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)'],creationflags=flags)
    supervisor=ProcessSupervisor()
    try:
        child=supervisor.launch([sys.executable,'-c','import time; time.sleep(60)'])
        supervisor.close()
        assert child.poll() is not None
        assert other.poll() is None
    finally:
        other.terminate();other.wait(timeout=5)


@pytest.mark.skipif(sys.platform!='win32',reason='Windows Job Object acceptance')
def test_child_removed_after_supervisor_owner_crash(tmp_path):
    import ctypes
    from ctypes import wintypes
    code="from local_vision_solver.process_supervisor import ProcessSupervisor; import sys,time; supervisor=ProcessSupervisor(); child=supervisor.launch([sys.executable,'-c','import time; time.sleep(60)']); print(child.pid,flush=True); time.sleep(60)"
    owner=subprocess.Popen([sys.executable,'-c',code],stdout=subprocess.PIPE,creationflags=subprocess.CREATE_NO_WINDOW)
    kernel=ctypes.WinDLL('kernel32')
    kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD];kernel.OpenProcess.restype=wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes=[wintypes.HANDLE,wintypes.DWORD];kernel.CloseHandle.argtypes=[wintypes.HANDLE]
    handle=None
    try:
        pid=int(owner.stdout.readline());handle=kernel.OpenProcess(0x100000,False,pid)
        assert handle
        owner.kill();owner.wait(timeout=5)
        assert kernel.WaitForSingleObject(handle,5000)==0
    finally:
        if owner.poll() is None:owner.kill();owner.wait(timeout=5)
        if handle:kernel.CloseHandle(handle)
