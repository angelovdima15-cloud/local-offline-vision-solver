from io import BytesIO
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import threading
import time
from uuid import UUID,uuid4
import zipfile

from PySide6.QtCore import QObject,Property,Signal,Slot,QUrl,QTimer
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QFileDialog
from .api_client import APIClient
from .setup_controller import SetupController
from ..app_paths import AppPaths
from ..config import product_config,save_config,load_config
from ..process_supervisor import ProcessSupervisor,choose_port
from ..storage import write_json,write_bytes
from ..windows_power import WindowsPower


class Controller(QObject):
    changed=Signal()
    updated=Signal(dict)
    activate=Signal()

    def __init__(self,paths,demo=False,parent=None):
        super().__init__(parent)
        self.paths,self.demo=paths.ensure(),demo
        self.setup=SetupController(paths,self)
        self.setup.finished.connect(self.startBackend)
        self._page='setup';self._message='Первоначальная настройка';self._ready=False
        self._tasks=[];self._clients=[];self._result={};self._pairingUrls=[];self._busy=False;self._qrRevision=0
        self.qr_bytes=b'';self.api=None;self.supervisor=None;self.backend=None;self.backend_log=None
        self.stop=threading.Event();self.power=None;self._powerEnabled=False
        self.persist_location=False;self.generation=0
        self.updated.connect(self.apply)
        if os.name=='nt':
            self.power=WindowsPower(paths.data/'power-state.json')
            try:self.power.recover()
            except Exception as exc:self._message='Восстановление питания: '+str(exc)
        if demo or (paths.data/'install-state.json').is_file():
            QTimer.singleShot(0,self.startBackend)

    @Property(str,notify=changed)
    def page(self):return self._page
    @Property(str,notify=changed)
    def message(self):return self._message
    @Property(bool,notify=changed)
    def ready(self):return self._ready
    @Property(bool,notify=changed)
    def busy(self):return self._busy
    @Property(bool,notify=changed)
    def isDemo(self):return self.demo
    @Property(bool,notify=changed)
    def powerEnabled(self):return self._powerEnabled
    @Property('QVariantList',notify=changed)
    def tasks(self):return self._tasks
    @Property('QVariantList',notify=changed)
    def clients(self):return self._clients
    @Property('QVariantList',notify=changed)
    def pairingUrls(self):return self._pairingUrls
    @Property('QVariantMap',notify=changed)
    def result(self):return self._result
    @Property(int,notify=changed)
    def qrRevision(self):return self._qrRevision
    @Property(str,notify=changed)
    def diskSpace(self):return f'{shutil.disk_usage(self.paths.data).free/1024**3:.1f} GiB свободно'
    @Property(str,notify=changed)
    def dataDirectory(self):return str(self.paths.data)

    @Slot(dict)
    def apply(self,value):
        for key in ('page','message','ready','busy','tasks','clients','result','pairingUrls','powerEnabled'):
            if key in value:setattr(self,'_'+key,value[key])
        if 'qr' in value:
            self.qr_bytes=value['qr'];self._qrRevision+=1
        self.changed.emit()

    def background(self,run):
        def work():
            try:run()
            except Exception as exc:
                self.updated.emit({'message':str(exc),'busy':False})
        threading.Thread(target=work,daemon=True).start()

    @Slot(str)
    def navigate(self,page):
        if page in {'setup','home','tasks','result','settings'}:
            self._page=page;self.changed.emit()

    @Slot()
    def chooseDataDirectory(self):
        if self.backend or self.setup.busy:return
        selected=QFileDialog.getExistingDirectory(None,'Каталог моделей, фотографий и результатов',str(self.paths.data))
        if selected:
            selected_path=Path(selected)
            if selected_path.name!='VisionSolver':selected_path=selected_path/'VisionSolver'
            self.paths=AppPaths.for_user(selected_path).ensure()
            if self.persist_location:
                bootstrap=AppPaths.default_root();bootstrap.mkdir(parents=True,exist_ok=True)
                write_json(bootstrap/'location.json',{'data_directory':str(self.paths.data)})
            self.setup.set_paths(self.paths)
            if self.power:self.power=WindowsPower(self.paths.data/'power-state.json')
            save_config(product_config(self.paths),self.paths.config)
            self.changed.emit()

    @Slot()
    def startBackend(self):
        if self._busy:return
        if self.backend and self.backend.poll() is None:
            if self._ready:return
            if self.supervisor:self.supervisor.close()
            self.backend=None
        self._busy=True;self._message='Запускаем локальную модель…';self.changed.emit()
        self.generation+=1;generation=self.generation
        def run():
            if not self.paths.config.exists():save_config(product_config(self.paths),self.paths.config)
            config=load_config(self.paths.config,self.paths.data)
            api_port=choose_port('0.0.0.0',8765,8775)
            inference_port=choose_port('127.0.0.1',8081,8091)
            secret=secrets.token_urlsafe(32)
            self.api=APIClient(f'http://127.0.0.1:{api_port}',secret)
            self.supervisor=ProcessSupervisor()
            command=[str(Path(sys.executable).parent/'VisionBackend.exe')] if getattr(sys,'frozen',False) else [sys.executable,'-m','local_vision_solver']
            command += ['--config',str(self.paths.config),'--data-dir',str(self.paths.data),'--api-port',str(api_port),'--inference-port',str(inference_port),'serve','--admin-stdin']
            if self.demo:command += ['--demo','--no-discovery']
            self.backend_log=(self.paths.logs/'backend-console.log').open('a',encoding='utf-8')
            self.backend=self.supervisor.launch(command,stdin=subprocess.PIPE,stdout=self.backend_log,cwd=str(self.paths.data))
            self.backend.stdin.write((json.dumps({'secret':secret})+'\n').encode());self.backend.stdin.close()
            deadline=time.monotonic()+310
            while time.monotonic()<deadline and not self.stop.is_set() and generation==self.generation:
                if self.backend.poll() is not None:raise RuntimeError('Backend остановился. Откройте logs/backend.log и runtime.log.')
                try:
                    self.api.get('/ready')
                    self.updated.emit({'ready':True,'busy':False,'page':'home','message':'Готово к работе' if not self.demo else 'TRANSPORT DEMO · без решения моделью'})
                    self.pair()
                    self.poll(generation)
                    return
                except Exception:self.stop.wait(1)
            raise RuntimeError('Запуск не завершился за 300 секунд. Повторите после проверки runtime.log.')
        self.background(run)

    def poll(self,generation):
        while not self.stop.wait(5) and generation==self.generation:
            try:
                if self.backend.poll() is not None:raise RuntimeError('Локальный backend остановился')
                health=self.api.get('/health')
                self.updated.emit({'tasks':self.api.get('/v1/admin/sessions'),'clients':self.api.get('/v1/admin/clients'),
                    'ready':health['status']=='ok','message':'Готово к работе' if health['status']=='ok' else 'Сервис временно недоступен'})
            except Exception as exc:self.updated.emit({'ready':False,'message':str(exc)})

    @Slot()
    def pair(self):
        def run():
            value=self.api.post('/v1/admin/pairing')
            urls=value['urls'] or [self.api.base+'/#pair='+value['token']]
            import qrcode
            data=BytesIO();qrcode.make(urls[0]).save(data,format='PNG')
            self.updated.emit({'pairingUrls':urls,'qr':data.getvalue(),'clients':self.api.get('/v1/admin/clients')})
        if self.api:self.background(run)

    @Slot()
    def addPhotos(self):
        if not self._ready:return
        filenames,_=QFileDialog.getOpenFileNames(None,'Связанные страницы задания','','Фото (*.jpg *.jpeg *.png *.heic *.heif *.webp *.tif *.tiff)')
        if not filenames:return
        def run():
            identifier=str(uuid4())
            self.api.post('/v1/sessions',{'session_id':identifier})
            for index,filename in enumerate(filenames,1):
                with open(filename,'rb') as handle:self.api.request('PUT',f'/v1/sessions/{identifier}/pages/{index}',content=handle)
            self.api.post(f'/v1/sessions/{identifier}/solve',{'page_count':len(filenames),'page_order':list(range(1,len(filenames)+1))})
            self.updated.emit({'page':'tasks','tasks':self.api.get('/v1/admin/sessions'),'message':'Задание отправлено в очередь'})
        self.background(run)

    @Slot(str)
    def openResult(self,identifier):
        UUID(identifier)
        def run():
            status=self.api.get('/v1/sessions/'+identifier)
            if status['result_available']:value=self.api.get('/v1/sessions/'+identifier+'/result')
            elif status['answer_available']:
                value={'session_id':identifier,'plain_text_answer':self.api.request('GET',f'/v1/sessions/{identifier}/answer.txt').text,'cards':[], 'output_error':status['output_error']}
            else:raise RuntimeError('Ответ ещё не готов')
            self.updated.emit({'result':value,'page':'result'})
        self.background(run)

    @Slot(str)
    def retryRender(self,identifier):
        UUID(identifier)
        self.background(lambda:self.api.post('/v1/sessions/'+identifier+'/render'))

    @Slot(str)
    def deleteTask(self,identifier):
        UUID(identifier)
        self.background(lambda:self.updated.emit({'tasks':self._delete_and_list(identifier)}))

    def _delete_and_list(self,identifier):
        self.api.request('DELETE','/v1/sessions/'+identifier)
        return self.api.get('/v1/admin/sessions')

    @Slot(str)
    def revokeClient(self,identifier):
        UUID(identifier)
        self.background(lambda:self.api.request('DELETE','/v1/admin/clients/'+identifier))

    @Slot(str,str)
    def download(self,identifier,kind):
        UUID(identifier)
        if kind not in {'txt','zip','png'}:return
        if kind=='png':selected=QFileDialog.getExistingDirectory(None,'Сохранить все PNG-карточки',str(Path.home()/'Downloads'))
        else:selected,_=QFileDialog.getSaveFileName(None,'Сохранить ответ',str(Path.home()/'Downloads'/f'vision-{identifier}.{kind}'))
        if not selected:return
        def run():
            if kind=='png':
                value=self.api.get(f'/v1/sessions/{identifier}/result')
                for card in value['cards']:
                    response=self.api.request('GET',f'/v1/sessions/{identifier}/cards/{card["index"]}')
                    write_bytes(Path(selected)/(identifier+'-'+card['file']),response.content)
                self.updated.emit({'message':'Все PNG сохранены: '+selected});return
            route='answer.txt' if kind=='txt' else 'package' if kind=='zip' else 'cards/1'
            response=self.api.request('GET',f'/v1/sessions/{identifier}/{route}')
            write_bytes(Path(selected),response.content)
            self.updated.emit({'message':'Сохранено: '+selected})
        self.background(run)

    @Slot(str)
    def openFolder(self,identifier):
        UUID(identifier)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.paths.sessions/identifier)))

    @Slot(bool)
    def setPower(self,enabled):
        try:
            if not self.power:raise RuntimeError('Режим доступен в Windows')
            if enabled:self.power.enable()
            else:self.power.disable()
            self._powerEnabled=enabled;self._message='Режим закрытой крышки включён для питания от сети' if enabled else 'Исходное действие крышки восстановлено';self.changed.emit()
        except Exception as exc:self._message='Настройка питания: '+str(exc);self.changed.emit()

    @Slot()
    def stopModel(self):
        self.generation+=1
        if self.supervisor:self.supervisor.close()
        self._ready=False;self._message='Модель остановлена';self.changed.emit()

    @Slot()
    def allowFirewall(self):
        if not self.api:return
        if not getattr(sys,'frozen',False):
            self._message='Настройка firewall доступна в установленной сборке';self.changed.emit();return
        import ctypes
        from urllib.parse import urlparse
        helper=Path(sys.executable).parent/'VisionFirewall.exe'
        code=ctypes.windll.shell32.ShellExecuteW(None,'runas',str(helper),'--port '+str(urlparse(self.api.base).port),str(helper.parent),0)
        self._message='Запрошен доступ только к API из локальной подсети' if code>32 else 'Windows не разрешила изменение firewall'
        self.changed.emit()

    @Slot()
    def openNetworkSettings(self):QDesktopServices.openUrl(QUrl('ms-settings:network-status'))
    @Slot()
    def openPowerSettings(self):QDesktopServices.openUrl(QUrl('ms-settings:powersleep'))
    @Slot()
    def openDriverPage(self):QDesktopServices.openUrl(QUrl('https://www.nvidia.com/Download/index.aspx'))

    @Slot()
    def installDriver(self):
        filename,_=QFileDialog.getOpenFileName(None,'Выберите официальный установщик NVIDIA','','Windows installer (*.exe)')
        if not filename:return
        def run():
            escaped=filename.replace("'","''")
            script="$s=Get-AuthenticodeSignature -LiteralPath '"+escaped+"'; if ($s.Status -ne 'Valid' -or $s.SignerCertificate.Subject -notmatch 'NVIDIA Corporation') { exit 1 }"
            response=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',script],capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW)
            if response.returncode:raise RuntimeError('Подпись официального установщика NVIDIA не подтверждена')
            import ctypes
            from ctypes import wintypes
            shell=ctypes.WinDLL('shell32');shell.ShellExecuteW.argtypes=[wintypes.HWND,wintypes.LPCWSTR,wintypes.LPCWSTR,wintypes.LPCWSTR,wintypes.LPCWSTR,ctypes.c_int];shell.ShellExecuteW.restype=wintypes.HINSTANCE
            write_json(self.paths.data/'driver-state.json',{'state':'installation_requested','resume_setup_after_reboot':True})
            if int(shell.ShellExecuteW(None,'runas',filename,None,str(Path(filename).parent),1) or 0)<=32:raise RuntimeError('Windows не разрешила запуск установщика драйвера')
            self.updated.emit({'message':'Установите драйвер в официальном мастере NVIDIA. Если потребуется, перезагрузите Windows и продолжите настройку Vision.'})
        self.background(run)

    @Slot()
    def exportDiagnostics(self):
        selected,_=QFileDialog.getSaveFileName(None,'Диагностика без фотографий','vision-diagnostics.zip')
        if not selected:return
        with zipfile.ZipFile(selected,'w',compression=zipfile.ZIP_DEFLATED) as archive:
            for path in self.paths.logs.glob('*.log*'):archive.write(path,'logs/'+path.name)
            archive.writestr('system.json',json.dumps(self.setup.report))

    def close(self):
        self.stop.set();self.setup.pause()
        if self.power:self.power.disable()
        if self.supervisor:self.supervisor.close()
        if self.backend_log:self.backend_log.close()
