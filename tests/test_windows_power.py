import json
import threading
from uuid import uuid4
import pytest
from local_vision_solver.windows_power import WindowsPower,ES_CONTINUOUS,ES_SYSTEM_REQUIRED


class FakePower:
    def __init__(self):self.scheme=uuid4();self.value=1;self.calls=[];self.writes=[]
    def active(self):return self.scheme
    def read(self,scheme):return self.value
    def write(self,scheme,value):self.value=value;self.writes.append(value)
    def activate(self,scheme):pass
    def execution(self,flags):self.calls.append((threading.get_ident(),flags))


def test_power_request_same_thread_and_ac_restore(tmp_path):
    api=FakePower();power=WindowsPower(tmp_path/'power.json',api)
    power.enable();assert api.value==0 and power.enabled
    power.disable();assert api.value==1 and not power.enabled
    assert [c[1] for c in api.calls]==[ES_CONTINUOUS|ES_SYSTEM_REQUIRED,ES_CONTINUOUS]
    assert len({c[0] for c in api.calls})==1


def test_crash_journal_restored_and_user_changes_preserved(tmp_path):
    api=FakePower();path=tmp_path/'power.json'
    first=WindowsPower(path,api);first.enable()
    first.stop.set();first.thread.join()
    WindowsPower(path,api).recover();assert api.value==1
    first.enable();api.value=2
    first.disable();assert api.value==2
    assert json.loads(path.read_text())['state']=='restored'


def test_failed_lid_write_never_enabled(tmp_path):
    api=FakePower()
    api.write=lambda *a: (_ for _ in ()).throw(PermissionError('organization policy'))
    power=WindowsPower(tmp_path/'power.json',api)
    with pytest.raises(PermissionError):power.enable()
    assert not power.enabled
