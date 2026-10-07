"""AC-only lid journal and a dedicated execution-state thread."""
import ctypes
from ctypes import wintypes
import json
import os
import threading
from uuid import UUID
from .storage import write_json

ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x1
SUB_BUTTONS = UUID('4f971e89-eebd-4455-a8de-9e59040e7347')
LID_ACTION = UUID('5ca83367-6e45-459f-a27b-476b1d01c936')


class GUID(ctypes.Structure):
    _fields_ = [('data',ctypes.c_ubyte*16)]
    @classmethod
    def from_uuid(cls,value):
        return cls((ctypes.c_ubyte*16).from_buffer_copy(value.bytes_le))
    def uuid(self):
        return UUID(bytes_le=bytes(self.data))


class PowerAPI:
    def __init__(self):
        if os.name != 'nt':
            raise RuntimeError('Windows power settings require Windows')
        self.powr = ctypes.WinDLL('powrprof',use_last_error=True)
        self.kernel = ctypes.WinDLL('kernel32',use_last_error=True)
        self.kernel.LocalFree.argtypes = [wintypes.HLOCAL]
        self.powr.PowerGetActiveScheme.argtypes = [wintypes.HKEY,ctypes.POINTER(ctypes.POINTER(GUID))]
        self.powr.PowerReadACValueIndex.argtypes = [wintypes.HKEY,ctypes.POINTER(GUID),ctypes.POINTER(GUID),ctypes.POINTER(GUID),ctypes.POINTER(wintypes.DWORD)]
        self.powr.PowerWriteACValueIndex.argtypes = [wintypes.HKEY,ctypes.POINTER(GUID),ctypes.POINTER(GUID),ctypes.POINTER(GUID),wintypes.DWORD]
        self.powr.PowerSetActiveScheme.argtypes = [wintypes.HKEY,ctypes.POINTER(GUID)]

    @staticmethod
    def checked(code):
        if code:
            raise OSError(code,ctypes.FormatError(code))

    def active(self):
        pointer = ctypes.POINTER(GUID)()
        self.checked(self.powr.PowerGetActiveScheme(None,ctypes.byref(pointer)))
        try:
            return pointer.contents.uuid()
        finally:
            self.kernel.LocalFree(ctypes.cast(pointer,wintypes.HLOCAL))

    def read(self,scheme):
        scheme,sub,setting = map(GUID.from_uuid,(scheme,SUB_BUTTONS,LID_ACTION))
        value = wintypes.DWORD()
        self.checked(self.powr.PowerReadACValueIndex(None,ctypes.byref(scheme),ctypes.byref(sub),ctypes.byref(setting),ctypes.byref(value)))
        return value.value

    def write(self,scheme,value):
        scheme,sub,setting = map(GUID.from_uuid,(scheme,SUB_BUTTONS,LID_ACTION))
        self.checked(self.powr.PowerWriteACValueIndex(None,ctypes.byref(scheme),ctypes.byref(sub),ctypes.byref(setting),value))

    def activate(self,scheme):
        value = GUID.from_uuid(scheme)
        self.checked(self.powr.PowerSetActiveScheme(None,ctypes.byref(value)))

    def execution(self,flags):
        if not self.kernel.SetThreadExecutionState(flags):
            raise ctypes.WinError(ctypes.get_last_error())


class WindowsPower:
    def __init__(self,journal,api=None):
        self.journal,self.api = journal,api or PowerAPI()
        self.enabled = False
        self.stop = threading.Event()
        self.thread = None
        self.execution_error = None

    def recover(self):
        if not self.journal.exists():
            return
        state = json.loads(self.journal.read_text(encoding='utf-8'))
        if state.get('state')!='applied':
            return
        scheme = UUID(state['scheme'])
        if self.api.read(scheme)==state['applied']:
            self.api.write(scheme,state['original'])
            if self.api.active()==scheme:
                self.api.activate(scheme)
            if self.api.read(scheme)!=state['original']:
                raise RuntimeError('Power setting restoration failed')
        write_json(self.journal,dict(state,state='restored'))

    def _keep_awake(self,ready):
        try:
            self.api.execution(ES_CONTINUOUS|ES_SYSTEM_REQUIRED)
            ready.set()
            self.stop.wait()
        except Exception as exc:
            self.execution_error = exc
            ready.set()
        finally:
            self.api.execution(ES_CONTINUOUS)

    def enable(self):
        if self.enabled:
            return
        self.recover()
        scheme = self.api.active()
        original = self.api.read(scheme)
        write_json(self.journal,{'state':'applied','scheme':str(scheme),'original':original,'applied':0})
        try:
            self.api.write(scheme,0)
            self.api.activate(scheme)
            if self.api.read(scheme)!=0:
                raise RuntimeError('Lid setting rejected by Windows policy')
            self.stop.clear()
            self.execution_error = None
            ready = threading.Event()
            self.thread = threading.Thread(target=self._keep_awake,args=(ready,),daemon=True,name='vision-power-request')
            self.thread.start()
            ready.wait(5)
            if self.execution_error or not ready.is_set():
                raise RuntimeError(str(self.execution_error or 'Power request failed'))
            self.enabled = True
        except BaseException:
            self.disable()
            raise

    def disable(self):
        self.stop.set()
        if self.thread:
            self.thread.join(timeout=5)
        self.recover()
        self.enabled = False
