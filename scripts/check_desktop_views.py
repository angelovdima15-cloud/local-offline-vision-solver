"""Render all QML views using API-verified demo data at Windows scale factors."""
import argparse
from datetime import datetime
from io import BytesIO
import json
import os
from pathlib import Path
import time
from uuid import uuid4

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scale',choices=['1','1.25','1.5','2'],default='1')
    args=parser.parse_args()
    os.environ.update(QT_QPA_PLATFORM='offscreen',QT_QUICK_BACKEND='software',QT_SCALE_FACTOR=args.scale)
    from PySide6.QtCore import QUrl,qInstallMessageHandler
    from PySide6.QtGui import QFontDatabase,QFont
    from PySide6.QtWidgets import QApplication
    from PySide6.QtQml import QQmlApplicationEngine
    from fastapi.testclient import TestClient
    from PIL import Image
    from local_vision_solver.app_paths import AppPaths
    from local_vision_solver.config import product_config
    from local_vision_solver.server import create_app
    from local_vision_solver.desktop.controller import Controller
    from local_vision_solver.desktop.main import Images
    import local_vision_solver.desktop.setup_controller as setup_module
    run=ROOT/'.cache/desktop-view-checks'/(datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid4().hex[:6]);run.mkdir(parents=True)
    paths=AppPaths.for_user(run/'data').ensure();config=product_config(paths);config.server.advertise=False
    app=QApplication([])
    for name in ('segoeui.ttf','seguisb.ttf','consola.ttf'):QFontDatabase.addApplicationFont('C:/Windows/Fonts/'+name)
    app.setFont(QFont('Segoe UI',11));messages=[];qInstallMessageHandler(lambda kind,context,message:messages.append(message))
    setup_module.computer_report=lambda paths:{'gpu':[{'name':'RTX 4060 Laptop','total_megabytes':8192}],
        'ram_gib':32,'disk_gib':64,'ram_ok':True,'disk_ok':True,'gpu_ok':True,'driver_ok':True,'os_ok':True}
    secret='isolated-qml-demo-admin-credential'
    api=create_app(config,demo=True,admin_secret=secret)
    with TestClient(api,base_url='http://127.0.0.1:8765',client=('127.0.0.1',9999),headers={'Authorization':'Bearer '+secret}) as client:
        identifier=client.post('/v1/sessions',json={}).json()['session_id']
        image=BytesIO();Image.new('RGB',(600,800),'white').save(image,format='JPEG')
        client.put(f'/v1/sessions/{identifier}/pages/1',content=image.getvalue()).raise_for_status()
        client.post(f'/v1/sessions/{identifier}/solve',json={'page_count':1,'page_order':[1]}).raise_for_status()
        deadline=time.monotonic()+10
        while time.monotonic()<deadline:
            status=client.get(f'/v1/sessions/{identifier}').json()
            if status['state']=='COMPLETE':break
            time.sleep(.02)
        assert status['state']=='COMPLETE'
        controller=Controller(paths)
        class Client:
            def request(self,method,path,**kwargs):
                response=client.request(method,path,**kwargs);response.raise_for_status();return response
            def get(self,path):return self.request('GET',path).json()
        controller.api=Client()
        result=client.get(f'/v1/sessions/{identifier}/result').json()
        controller.apply({'ready':True,'tasks':[status],'result':result,'clients':[{'id':str(uuid4()),'name':'iPhone Safari'}]})
        engine=QQmlApplicationEngine();engine.rootContext().setContextProperty('vision',controller);engine.rootContext().setContextProperty('setup',controller.setup)
        engine.addImageProvider('vision',Images(controller))
        engine.load(QUrl.fromLocalFile(str(ROOT/'src/local_vision_solver/desktop/qml/Main.qml')))
        assert engine.rootObjects()
        window=engine.rootObjects()[0];window.setWidth(900);window.setHeight(640)
        for view in ('setup','home','tasks','result','settings'):
            controller.navigate(view)
            for _ in range(12):app.processEvents();time.sleep(.03)
            assert window.grabWindow().save(str(run/(view+'.png')))
        controller.close();window.hide()
        engine.deleteLater();app.processEvents()
    errors=[message for message in messages if any(marker in message for marker in ('ReferenceError','TypeError','Unable to assign','is not a type','Cannot read'))]
    (run/'qml.log').write_text('\n'.join(messages),encoding='utf-8')
    (run/'report.json').write_text(json.dumps({'scale':args.scale,'views':5,'passed':not errors,'demo':True},indent=2),encoding='utf-8')
    print(f'QML views: {"PASS" if not errors else "FAIL"}; scale={args.scale}; log={run/"qml.log"}')
    if errors:print('\n'.join(errors))
    return 1 if errors else 0


if __name__=='__main__':raise SystemExit(main())
