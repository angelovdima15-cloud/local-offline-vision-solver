import ctypes
import os
import shutil
import threading
import platform
from PySide6.QtCore import QObject,Signal,Property,Slot
from ..asset_installer import AssetInstaller,DownloadPaused
from ..resources import gpu_snapshot


def computer_report(paths):
    memory=None
    if os.name=='nt':
        class Memory(ctypes.Structure):
            _fields_=[('length',ctypes.c_ulong),('load',ctypes.c_ulong)]+[(x,ctypes.c_ulonglong) for x in ('total','available','page_total','page_available','virtual_total','virtual_available','extended')]
        value=Memory();value.length=ctypes.sizeof(value)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(value)):
            memory=value.total
    paths.ensure()
    gpu=gpu_snapshot()
    free=shutil.disk_usage(paths.data).free
    return {'windows':os.name=='nt','ram_gib':round(memory/1024**3,1) if memory else None,
            'gpu':gpu,'disk_gib':round(free/1024**3,1),
            'disk_ok':free>=20*1024**3,'ram_ok':bool(memory and memory>=15*1024**3),
            'gpu_ok':any(g['total_megabytes']>=7500 for g in gpu),
            'driver_ok':any(tuple(map(int,g['driver_version'].split('.'))) >= (551,61) for g in gpu),
            'os_ok':os.name=='nt' and sys_windows_build()>=22000 and platform.machine().upper() in {'AMD64','X86_64'}}


def sys_windows_build():
    import sys
    return sys.getwindowsversion().build if os.name=='nt' else 0


class SetupController(QObject):
    changed=Signal()
    updated=Signal(dict)
    finished=Signal()

    def __init__(self,paths,parent=None):
        super().__init__(parent)
        self.paths=paths
        self._message='Проверяем компьютер…'
        self._progress=0.0
        self._busy=False
        self._report={}
        self.installer=None
        self.updated.connect(self.apply)
        self.check()

    @Property(str,notify=changed)
    def message(self):return self._message
    @Property(float,notify=changed)
    def progress(self):return self._progress
    @Property(bool,notify=changed)
    def busy(self):return self._busy
    @Property('QVariantMap',notify=changed)
    def report(self):return self._report
    @Property(str,notify=changed)
    def dataDirectory(self):return str(self.paths.data)

    @Slot(dict)
    def apply(self,value):
        if 'report' in value:self._report=value['report']
        if 'message' in value:self._message=value['message']
        if 'busy' in value:self._busy=value['busy']
        if 'progress' in value:self._progress=value['progress']
        self.changed.emit()
        if value.get('finished'):self.finished.emit()

    @Slot()
    def check(self):
        def run():
            try:
                import logging
                logging.getLogger('vision.setup').info('Beginning pinned asset setup')
                self.updated.emit({'report':computer_report(self.paths),'message':'Выберите каталог данных и начните настройку.'})
            except Exception as exc:self.updated.emit({'message':str(exc)})
        threading.Thread(target=run,daemon=True).start()

    def set_paths(self,paths):
        if self._busy:raise RuntimeError('Pause setup before changing data location')
        self.paths=paths;self.changed.emit();self.check()

    @Slot()
    def install(self):
        if self._busy:return
        self._busy=True;self.changed.emit()
        def progress(value):
            labels={'downloading':'Загрузка','verifying':'Проверка SHA256'}
            percent=value['bytes']/value['total']
            speed=value['speed']/1024**2
            eta='' if value['eta'] is None else f" · осталось {int(value['eta']//60)} мин"
            self.updated.emit({'progress':percent,'message':f"{labels.get(value['stage'],value['stage'])}: {value['asset_id']} · {percent:.0%} · {speed:.1f} MiB/с{eta}"})
        self.installer=AssetInstaller(self.paths,progress=progress)
        def run():
            try:
                if shutil.disk_usage(self.paths.data).free<20*1024**3 and not (self.paths.data/'install-state.json').exists():
                    raise OSError('Нужно минимум 20 GiB свободного места. Выберите другой диск.')
                self.installer.install()
                self.updated.emit({'busy':False,'progress':1.0,'message':'Файлы проверены. Запускаем модель…','finished':True})
            except DownloadPaused:self.updated.emit({'busy':False,'message':'Загрузка приостановлена. Нажмите «Продолжить».'})
            except Exception as exc:self.updated.emit({'busy':False,'message':'Настройка не завершена: '+str(exc)})
        threading.Thread(target=run,daemon=True,name='vision-asset-setup').start()

    @Slot()
    def pause(self):
        if self.installer:self.installer.pause.set()

    @Slot()
    def restartDownloads(self):
        if self._busy:return
        if not self.installer:self.installer=AssetInstaller(self.paths)
        for asset in self.installer.assets:
            self.installer.restart_download(asset.asset_id)
        self._message='Неполные загрузки удалены. Нажмите «Продолжить».';self.changed.emit()
