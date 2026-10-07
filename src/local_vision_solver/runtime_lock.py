"""All callers using the same inference endpoint share a user-wide OS lock."""
import hashlib
import os
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlparse
from .app_paths import AppPaths
from .locking import file_lock


def runtime_lock(endpoint: str):
    url = urlparse(endpoint)
    key = f"{url.hostname.lower()}:{url.port}"
    if os.name == 'nt':
        return named_mutex('Local\\VisionInference-' + hashlib.sha256(key.encode()).hexdigest())
    root = AppPaths.for_user().data / "locks"
    return file_lock(root / (hashlib.sha256(key.encode()).hexdigest() + ".lock"))


def runtime_process_lock(endpoint):
    key=hashlib.sha256(endpoint.encode()).hexdigest()
    if os.name=='nt':return named_mutex('Local\\VisionRuntime-'+key)
    return file_lock(AppPaths.for_user().data/'locks'/('runtime-'+key+'.lock'))


@contextmanager
def named_mutex(name):
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateMutexW.argtypes = [wintypes.LPVOID,wintypes.BOOL,wintypes.LPCWSTR]
    kernel.CreateMutexW.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE,wintypes.DWORD]
    kernel.ReleaseMutex.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.CreateMutexW(None,False,name)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    acquired = False
    try:
        result = kernel.WaitForSingleObject(handle,0)
        if result not in {0,0x80}:
            raise RuntimeError('Another session is using this model')
        acquired = True
        yield
    finally:
        if acquired:
            kernel.ReleaseMutex(handle)
        kernel.CloseHandle(handle)
