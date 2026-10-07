"""Install/update/uninstall in an isolated directory; retain isolated user data."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import subprocess
import sys
from uuid import uuid4
import winreg

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--installer',type=Path,required=True)
    args=parser.parse_args()
    key=r'Software\Microsoft\Windows\CurrentVersion\Uninstall\{944EB08E-3B20-4C0B-AC3E-2C85DB5B6C2E}_is1'
    try:existing=winreg.OpenKey(winreg.HKEY_CURRENT_USER,key)
    except FileNotFoundError:existing=None
    if existing:
        existing.Close();raise RuntimeError('An installed Vision exists; use a clean Windows account for the installer check')
    run=ROOT/'.cache/installer-checks'/(datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid4().hex[:6]);run.mkdir(parents=True)
    target=(run/'Программа с пробелами').resolve()
    if not target.is_relative_to(run.resolve()):raise ValueError('Invalid installer test path')
    data=run/'isolated-data';data.mkdir();(data/'sentinel.txt').write_text('preserve photographs and settings',encoding='utf-8')
    from local_vision_solver.app_paths import AppPaths
    from local_vision_solver.config import product_config,save_config
    paths=AppPaths.for_user(data).ensure();save_config(product_config(paths),paths.config)
    (paths.models/'sentinel.gguf').write_bytes(b'preserve existing model')
    (paths.sessions/'sentinel-photo.jpg').write_bytes(b'preserve existing photograph')
    def command(args,name):
        with (run/(name+'.log')).open('w',encoding='utf-8') as log:
            result=subprocess.run(list(map(str,args)),stdout=log,stderr=subprocess.STDOUT,timeout=300,creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode:raise RuntimeError(f'{name} failed: exit={result.returncode}; log={run/(name+".log")}')
    installer=args.installer.resolve()
    try:
        for name in ('install','update'):
            command([installer,'/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/CURRENTUSER','/DIR='+str(target),'/LOG='+str(run/(name+'-inno.log'))],name)
            assert (target/'VisionApp.exe').is_file() and (target/'VisionBackend.exe').is_file()
            assert (data/'sentinel.txt').read_text(encoding='utf-8')=='preserve photographs and settings'
            assert (paths.models/'sentinel.gguf').read_bytes()==b'preserve existing model'
            assert (paths.sessions/'sentinel-photo.jpg').read_bytes()==b'preserve existing photograph'
            command([target/'VisionApp.exe','--data-dir',data,'--demo','--smoke',run/(name+'-gui.png')],name+'-gui')
        command([sys.executable,ROOT/'scripts/check_desktop.py','--executable',target/'VisionApp.exe'],'gui-setup')
        command([sys.executable,ROOT/'scripts/check_desktop.py','--executable',target/'VisionApp.exe','--demo'],'gui-demo')
        command([sys.executable,ROOT/'scripts/acceptance_http.py','--executable',target/'VisionBackend.exe'],'http')
        command([sys.executable,ROOT/'scripts/check_desktop.py','--executable',target/'VisionApp.exe','--demo'],'gui-relaunch')
    finally:
        uninstaller=target/'unins000.exe'
        if uninstaller.is_file():command([uninstaller,'/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/LOG='+str(run/'uninstall-inno.log')],'uninstall')
    assert (data/'sentinel.txt').is_file()
    assert (paths.models/'sentinel.gguf').is_file() and (paths.sessions/'sentinel-photo.jpg').is_file()
    report={'installer_update_uninstall':'passed','frozen_gui_http':'passed','isolated_data_preserved':True,
            'clean_windows_without_python':False,'hardware_acceptance_complete':False}
    (run/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print('Installer check PASS; report='+str(run/'report.json'))
    return 0


if __name__=='__main__':raise SystemExit(main())
