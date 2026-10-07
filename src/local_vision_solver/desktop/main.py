import argparse
import hashlib
import os
from pathlib import Path
import sys
from PySide6.QtCore import QUrl,QTimer,QLockFile,Qt,QAbstractNativeEventFilter,qInstallMessageHandler
from PySide6.QtGui import QIcon,QImage,QFontDatabase,QFont
from PySide6.QtNetwork import QLocalServer,QLocalSocket
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickImageProvider
from PySide6.QtWidgets import QApplication,QSystemTrayIcon,QMenu
from .controller import Controller
from ..app_paths import AppPaths
from ..logging_setup import configure_logging


class Images(QQuickImageProvider):
    def __init__(self,controller):
        super().__init__(QQuickImageProvider.Image)
        self.controller=controller

    def requestImage(self,identifier,size,requestedSize):
        image=QImage()
        try:
            if identifier.startswith('qr'):
                image.loadFromData(self.controller.qr_bytes)
            else:
                parts=identifier.split('/')
                if parts[0]=='card':
                    route=f'/v1/sessions/{parts[1]}/cards/{int(parts[2])}'
                elif parts[0]=='page':
                    route=f'/v1/sessions/{parts[1]}/pages/{int(parts[2])}/preview'
                else:return image
                image.loadFromData(self.controller.api.request('GET',route).content)
            if requestedSize.width()>0 and requestedSize.height()>0:
                image=image.scaled(requestedSize,Qt.KeepAspectRatio,Qt.SmoothTransformation)
            size.setWidth(image.width());size.setHeight(image.height())
        except Exception:
            pass
        return image


def main(argv=None):
    parser=argparse.ArgumentParser(description='Vision Windows desktop')
    parser.add_argument('--data-dir',type=Path)
    parser.add_argument('--demo',action='store_true')
    parser.add_argument('--smoke',type=Path,help='Headless QML screenshot and exit; development acceptance only')
    parser.add_argument('--uninstall-cleanup',action='store_true')
    parser.add_argument('--delete-data',action='store_true')
    args=parser.parse_args(argv)
    paths=AppPaths.for_user(args.data_dir)
    if args.uninstall_cleanup:
        from ..windows_power import WindowsPower
        WindowsPower(paths.data/'power-state.json').recover()
        if args.delete_data:
            import shutil
            if paths.data in {Path.home().resolve(),Path(paths.data.anchor),Path(os.environ.get('WINDIR','C:/Windows')).resolve()}:
                raise ValueError('Invalid data removal path')
            if paths.config.is_file():
                from ..config import load_config
                if load_config(paths.config).data_directory!=paths.data:
                    raise ValueError('Data directory does not match app configuration')
                shutil.rmtree(paths.data)
                pointer=AppPaths.default_root()/'location.json'
                if pointer.is_file() and Path(__import__('json').loads(pointer.read_text(encoding='utf-8'))['data_directory']).resolve()==paths.data:
                    pointer.unlink()
        return 0
    paths.ensure()
    if args.smoke:
        os.environ['QT_QPA_PLATFORM']='offscreen'
        os.environ['QT_QUICK_BACKEND']='software'
    configure_logging(paths.logs,'app')
    import logging
    qInstallMessageHandler(lambda kind,context,message:logging.getLogger('vision.qt').warning(message))
    app=QApplication(sys.argv[:1]);app.setApplicationName('Vision');app.setOrganizationName('VisionSolver');app.setQuitOnLastWindowClosed(False)
    for name in ('segoeui.ttf','seguisb.ttf','consola.ttf'):
        font=Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts'/name
        if font.exists():QFontDatabase.addApplicationFont(str(font))
    app.setFont(QFont('Segoe UI',11))
    key='Vision-'+hashlib.sha256(str(paths.data).casefold().encode()).hexdigest()[:24]
    lock=QLockFile(str(paths.data/'.desktop.lock'))
    if not lock.tryLock(100):
        socket=QLocalSocket();socket.connectToServer(key)
        if socket.waitForConnected(2000):socket.write(b'activate');socket.waitForBytesWritten(1000)
        return 0
    server=QLocalServer();QLocalServer.removeServer(key)
    if not server.listen(key):raise RuntimeError('Cannot create desktop activation channel')
    controller=Controller(paths,args.demo)
    controller.persist_location=args.data_dir is None
    engine=QQmlApplicationEngine()
    engine.rootContext().setContextProperty('vision',controller)
    engine.rootContext().setContextProperty('setup',controller.setup)
    engine.addImageProvider('vision',Images(controller))
    engine.load(QUrl.fromLocalFile(str(Path(__file__).parent/'qml'/'Main.qml')))
    if not engine.rootObjects():
        controller.close();return 2
    window=engine.rootObjects()[0]
    class PowerEvents(QAbstractNativeEventFilter):
        def nativeEventFilter(self,event_type,message):
            if os.name=='nt':
                import ctypes
                from ctypes import wintypes
                value=ctypes.cast(int(message),ctypes.POINTER(wintypes.MSG)).contents
                if value.message==0x218:
                    if value.wParam==4:controller.stopModel()
                    elif value.wParam in {7,18}:QTimer.singleShot(0,controller.startBackend)
            return False,0
    power_events=PowerEvents();app.installNativeEventFilter(power_events)
    def activate():window.show();window.raise_();window.requestActivate()
    controller.activate.connect(activate)
    def incoming():
        socket=server.nextPendingConnection();socket.disconnectFromServer();activate()
    server.newConnection.connect(incoming)
    icon=QIcon(str(Path(__file__).parents[1]/'web'/'icon.svg'))
    window.setIcon(icon)
    tray=QSystemTrayIcon(icon,app);tray.setToolTip('Vision · локальное решение заданий')
    menu=QMenu()
    menu.addAction('Открыть приложение',activate)
    menu.addAction('Подключить телефон',lambda:(activate(),controller.navigate('home'),controller.pair()))
    action=menu.addAction('Работать с закрытой крышкой');action.setCheckable(True);action.toggled.connect(controller.setPower)
    controller.changed.connect(lambda:action.setChecked(controller.powerEnabled))
    menu.addAction('Остановить модель',controller.stopModel)
    menu.addSeparator()
    def quit_app():
        controller.close();tray.hide();app.quit()
    menu.addAction('Выход',quit_app);tray.setContextMenu(menu)
    tray.activated.connect(lambda reason:activate() if reason==QSystemTrayIcon.Trigger else None)
    if not args.smoke:tray.show()
    explained=False
    def hidden():
        nonlocal explained
        if not window.isVisible() and not explained:
            tray.showMessage('Vision работает в трее','Модель продолжает работать. Для полного завершения выберите «Выход».')
            explained=True
    window.visibleChanged.connect(hidden)
    if args.smoke:
        exit_code=[0]
        def capture():
            args.smoke.parent.mkdir(parents=True,exist_ok=True)
            if not window.grabWindow().save(str(args.smoke)):exit_code[0]=3
            quit_app()
        deadline=[0]
        def capture_ready():
            deadline[0]+=1
            if not args.demo or controller.ready: capture()
            elif deadline[0]>=25:exit_code[0]=4;quit_app()
            else:QTimer.singleShot(1000,capture_ready)
        QTimer.singleShot(2000,capture_ready)
    result=app.exec()
    controller.close();server.close();lock.unlock()
    return exit_code[0] if args.smoke else result


if __name__=='__main__':raise SystemExit(main())
