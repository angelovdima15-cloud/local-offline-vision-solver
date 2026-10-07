"""Own only explicitly launched processes. Windows Job Object kills descendants."""
import ctypes
from ctypes import wintypes
import os
import socket
import subprocess
import threading
import time
import httpx


def choose_port(host,start,end):
    for port in range(start,end+1):
        with socket.socket(socket.AF_INET,socket.SOCK_STREAM) as sock:
            try:
                if os.name == 'nt':
                    sock.setsockopt(socket.SOL_SOCKET,socket.SO_EXCLUSIVEADDRUSE,1)
                sock.bind((host,port))
                return port
            except OSError:
                pass
    raise RuntimeError('Нет свободного порта')


def owns_port(pid,port):
    if os.name!='nt':return True
    iphelper=ctypes.WinDLL('iphlpapi')
    iphelper.GetExtendedTcpTable.argtypes=[wintypes.LPVOID,ctypes.POINTER(wintypes.DWORD),wintypes.BOOL,wintypes.ULONG,ctypes.c_int,wintypes.ULONG]
    class Row4(ctypes.Structure):
        _fields_=[(name,wintypes.DWORD) for name in ('state','local_address','local_port','remote_address','remote_port','pid')]
    class Row6(ctypes.Structure):
        _fields_=[('local_address',ctypes.c_ubyte*16),('local_scope',wintypes.DWORD),('local_port',wintypes.DWORD),
                  ('remote_address',ctypes.c_ubyte*16),('remote_scope',wintypes.DWORD),('remote_port',wintypes.DWORD),
                  ('state',wintypes.DWORD),('pid',wintypes.DWORD)]
    for family,row_type in ((2,Row4),(23,Row6)):
        length=wintypes.DWORD()
        iphelper.GetExtendedTcpTable(None,ctypes.byref(length),False,family,3,0)
        buffer=ctypes.create_string_buffer(length.value)
        if iphelper.GetExtendedTcpTable(buffer,ctypes.byref(length),False,family,3,0):continue
        count=ctypes.cast(buffer,ctypes.POINTER(wintypes.DWORD)).contents.value
        rows=ctypes.cast(ctypes.addressof(buffer)+ctypes.sizeof(wintypes.DWORD),ctypes.POINTER(row_type))
        for index in range(count):
            row=rows[index]
            if row.pid==pid and socket.ntohs(row.local_port & 0xffff)==port:return True
    return False


class WindowsJob:
    def __init__(self):
        self.handle = None
        if os.name != 'nt':
            return
        class Basic(ctypes.Structure):
            _fields_ = [('PerProcessUserTimeLimit',ctypes.c_longlong),('PerJobUserTimeLimit',ctypes.c_longlong),
                ('LimitFlags',wintypes.DWORD),('MinimumWorkingSetSize',ctypes.c_size_t),('MaximumWorkingSetSize',ctypes.c_size_t),
                ('ActiveProcessLimit',wintypes.DWORD),('Affinity',ctypes.c_size_t),('PriorityClass',wintypes.DWORD),('SchedulingClass',wintypes.DWORD)]
        class IO(ctypes.Structure):
            _fields_ = [(name,ctypes.c_ulonglong) for name in ('ReadOperationCount','WriteOperationCount','OtherOperationCount','ReadTransferCount','WriteTransferCount','OtherTransferCount')]
        class Extended(ctypes.Structure):
            _fields_ = [('BasicLimitInformation',Basic),('IoInfo',IO),('ProcessMemoryLimit',ctypes.c_size_t),('JobMemoryLimit',ctypes.c_size_t),
                        ('PeakProcessMemoryUsed',ctypes.c_size_t),('PeakJobMemoryUsed',ctypes.c_size_t)]
        kernel = self.kernel = ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.CreateJobObjectW.argtypes = [wintypes.LPVOID,wintypes.LPCWSTR]
        kernel.CreateJobObjectW.restype = wintypes.HANDLE
        kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE,ctypes.c_int,wintypes.LPVOID,wintypes.DWORD]
        kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE,wintypes.HANDLE]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.TerminateJobObject.argtypes = [wintypes.HANDLE,wintypes.UINT]
        self.handle = kernel.CreateJobObjectW(None,None)
        info = Extended()
        info.BasicLimitInformation.LimitFlags = 0x2000  # KILL_ON_JOB_CLOSE
        if not self.handle or not kernel.SetInformationJobObject(self.handle,9,ctypes.byref(info),ctypes.sizeof(info)):
            self.close()
            raise ctypes.WinError(ctypes.get_last_error())

    def assign(self,process):
        if self.handle and not self.kernel.AssignProcessToJobObject(self.handle,wintypes.HANDLE(int(process._handle))):
            raise ctypes.WinError(ctypes.get_last_error())

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


class ProcessSupervisor:
    def __init__(self):
        self.job = WindowsJob()
        self.processes = []
        self.stop = threading.Event()

    def launch(self,args,*,stdin=None,stdout=None,cwd=None):
        flags = (subprocess.CREATE_NO_WINDOW | 0x4) if os.name == 'nt' else 0
        process = subprocess.Popen(args,stdin=stdin,stdout=stdout,stderr=subprocess.STDOUT,
                                   cwd=cwd,creationflags=flags)
        try:
            self.job.assign(process)
            if os.name == 'nt':
                # Resume only after job assignment; no orphan window exists at startup.
                ntdll = ctypes.WinDLL('ntdll')
                ntdll.NtResumeProcess.argtypes = [wintypes.HANDLE]
                ntdll.NtResumeProcess.restype = ctypes.c_long
                if ntdll.NtResumeProcess(wintypes.HANDLE(int(process._handle))) < 0:
                    raise RuntimeError('Cannot resume owned process')
        except BaseException:
            process.kill()
            process.wait()
            raise
        self.processes.append(process)
        return process

    def wait_ready(self,process,url,timeout=300):
        deadline = time.monotonic()+timeout
        with httpx.Client(timeout=2,trust_env=False) as client:
            while time.monotonic()<deadline and not self.stop.is_set():
                if process.poll() is not None:
                    raise RuntimeError('model_crash: '+str(process.returncode))
                try:
                    from urllib.parse import urlparse
                    if not owns_port(process.pid,urlparse(url).port):
                        self.stop.wait(.5);continue
                    response = client.get(url+'/health')
                    if response.status_code==200 and response.json().get('status')=='ok':
                        return
                except (httpx.HTTPError,ValueError):
                    pass
                self.stop.wait(.5)
        raise RuntimeError('model_startup_timeout')

    def terminate(self,process):
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)

    def close(self):
        self.stop.set()
        self.job.close()
        for process in reversed(self.processes):
            self.terminate(process)


class ModelMonitor:
    def __init__(self,config,supervisor,process,manager):
        self.config,self.supervisor,self.process,self.manager = config,supervisor,process,manager
        self.attempts = 0
        self.thread = threading.Thread(target=self.run,daemon=True,name='vision-model-monitor')

    def run(self):
        from .runtime import launch_server
        from .job_repository import StorageUnavailable
        while not self.supervisor.stop.wait(5):
            healthy = self.process.poll() is None
            if healthy:
                try:
                    with httpx.Client(timeout=2,trust_env=False) as client:
                        healthy = client.get(self.config.inference.endpoint+'/health').status_code==200
                except httpx.HTTPError:
                    healthy = False
            self.manager.model_ready = healthy
            if healthy:
                continue
            for row in self.manager.repository.all():
                if row['state']=='RUNNING':
                    self.manager.repository.update(row['id'],state='ERROR',error_code='model_crash',error_message='Модель остановилась во время решения. Отправьте фото заново.')
            if self.attempts>=3:
                return
            delay = (2,5,15)[self.attempts]
            self.attempts += 1
            if self.supervisor.stop.wait(delay):
                return
            try:
                self.supervisor.terminate(self.process)
                self.process = launch_server(self.config,supervisor=self.supervisor)
                self.supervisor.wait_ready(self.process,self.config.inference.endpoint)
                self.manager.model_ready = True
                self.manager.wake.set()
            except (RuntimeError,OSError,StorageUnavailable):
                self.manager.model_ready = False
