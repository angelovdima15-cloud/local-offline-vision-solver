"""Build the onedir desktop/backend payload and one per-user Vision.exe installer."""
import argparse
from datetime import datetime,timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from uuid import uuid4

ROOT=Path(__file__).resolve().parents[1]


def checksum_file(path):
    with path.open('rb') as handle:return hashlib.file_digest(handle,'sha256').hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--iscc',type=Path)
    parser.add_argument('--browser-executable',type=Path)
    parser.add_argument('--payload-only',action='store_true')
    parser.add_argument('--check-installer',action='store_true')
    args=parser.parse_args()
    if os.name!='nt':raise RuntimeError('Build on Windows x64')
    stage=ROOT/'.cache/windows-build'/uuid4().hex[:8];stage.mkdir(parents=True)
    dist=stage/'dist';build=stage/'build';payload=stage/'payload';payload.mkdir()
    log=stage/'build.log'
    common=[sys.executable,'-m','PyInstaller','--noconfirm','--clean','--onedir','--paths',str(ROOT/'src'),
            '--distpath',str(dist),'--workpath',str(build),'--specpath',str(stage),
            '--exclude-module','pytest','--exclude-module','playwright','--exclude-module','IPython',
            '--add-data',str(ROOT/'src/local_vision_solver/assets.lock.json')+';local_vision_solver']
    with log.open('w',encoding='utf-8') as output:
        builds=[['--name','VisionBackend','--exclude-module','PySide6','--collect-submodules','uvicorn','--collect-submodules','zeroconf',
                 '--collect-submodules','pillow_heif','--collect-submodules','qrcode',
                 '--add-data',str(ROOT/'src/local_vision_solver/web')+';local_vision_solver/web',str(ROOT/'scripts/frozen_backend.py')],
                ['--name','VisionApp','--windowed','--add-data',str(ROOT/'src/local_vision_solver/desktop/qml')+';local_vision_solver/desktop/qml',
                 '--add-data',str(ROOT/'src/local_vision_solver/web/icon.svg')+';local_vision_solver/web',str(ROOT/'scripts/frozen_desktop.py')],
                ['--name','VisionFirewall','--windowed','--uac-admin',str(ROOT/'scripts/frozen_firewall.py')]]
        for options in builds:
            result=subprocess.run([*common,*options],cwd=ROOT,stdout=output,stderr=subprocess.STDOUT)
            if result.returncode:
                print(f'Freeze failed; exit={result.returncode}; log={log}');return result.returncode
    for name in ('VisionBackend','VisionApp','VisionFirewall'):
        shutil.copytree(dist/name,payload,dirs_exist_ok=True)
    notices=['VisionSolver 0.4.0 ? third-party components','Python and Qt libraries are dynamically bundled. Development tools and model assets are not bundled.','Qt/PySide6: LGPLv3/GPLv3; https://www.qt.io/licensing/ and https://code.qt.io/pyside/pyside-setup.git','llama.cpp: MIT; https://github.com/ggml-org/llama.cpp','Qwen3-VL GGUF: Apache-2.0; https://huggingface.co/Qwen/Qwen3-VL-8B-Instruct-GGUF']
    licenses=payload/'licenses';licenses.mkdir()
    product={'httpx','httpcore','pydantic','pydantic-core','pillow','numpy','opencv-python-headless','matplotlib','sympy','fastapi','starlette','uvicorn','zeroconf','ifaddr','pillow-heif','qrcode','pyside6','pyside6-essentials','pyside6-addons','shiboken6','anyio','certifi','idna','h11','contourpy','cycler','fonttools','kiwisolver','packaging','pyparsing','python-dateutil','six','mpmath','typing-extensions','typing-inspection','annotated-types','annotated-doc','click','colorama'}
    for distribution in importlib.metadata.distributions():
        name=distribution.metadata['Name'];normalized=name.lower().replace('_','-')
        if normalized not in product:continue
        notices.append(name+' '+distribution.version+' ? '+str(distribution.metadata.get('License-Expression') or distribution.metadata.get('License') or 'See bundled license files'))
        for item in distribution.files or []:
            if 'license' in str(item).lower() or 'copying' in str(item).lower():
                source=Path(distribution.locate_file(item))
                if source.is_file() and source.stat().st_size<4*1024**2:
                    target=licenses/normalized/str(item).replace('../','')
                    target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
    python_license=Path(sys.base_prefix)/'LICENSE.txt'
    if python_license.is_file():shutil.copy2(python_license,licenses/'Python-LICENSE.txt')
    (payload/'THIRD_PARTY_NOTICES.txt').write_text('\n'.join(notices)+'\n',encoding='utf-8')
    def check(script,*options):
        result=subprocess.run([sys.executable,'scripts/'+script,*map(str,options)],cwd=ROOT)
        if result.returncode:raise RuntimeError('Required check failed: '+script)
    check('acceptance_http.py','--executable',payload/'VisionBackend.exe')
    browser=['--browser-executable',str(args.browser_executable)] if args.browser_executable else []
    check('check_browser.py','--executable',payload/'VisionBackend.exe',*browser)
    check('check_desktop.py','--executable',payload/'VisionApp.exe')
    check('check_desktop.py','--executable',payload/'VisionApp.exe','--demo')
    destination=ROOT/'dist';destination.mkdir(exist_ok=True)
    manifest={'version':'0.4.0','kind':'per-user Windows 11 x64 installer','created_at':datetime.now(timezone.utc).isoformat(),
              'payload':str(payload),'model_assets_included':False,'hardware_acceptance_complete':False,
              'frozen_http_browser_gui_checks':'passed','files':{p.relative_to(payload).as_posix():checksum_file(p) for p in payload.rglob('*') if p.is_file()}}
    if not args.payload_only:
        iscc=args.iscc or ROOT/'.cache/build-tools/Inno/ISCC.exe'
        if not iscc.is_file():raise RuntimeError('Inno compiler missing; payload is ready at '+str(payload))
        with (stage/'installer.log').open('w',encoding='utf-8') as output:
            result=subprocess.run([str(iscc),'/DPayloadDir='+str(payload),'/DOutputDir='+str(destination),str(ROOT/'installer/Vision.iss')],stdout=output,stderr=subprocess.STDOUT,cwd=ROOT)
        if result.returncode:raise RuntimeError('Installer build failed; log='+str(stage/'installer.log'))
        installer=destination/'Vision.exe';sha=checksum_file(installer)
        installer.with_suffix('.exe.sha256').write_text(sha+'  Vision.exe\n',encoding='ascii')
        manifest['installer_sha256']=sha
        if args.check_installer:check('check_installer.py','--installer',installer)
    (destination/'release-manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    (destination/'acceptance-report.json').write_text(json.dumps({'software_checks':'passed','hardware_acceptance_complete':False,'release_ready':False,
        'pending':['RTX 4060 Laptop 8 GB real Qwen workload','iPhone Safari and hotspot','clean Windows without Python','offline model solve after setup','closed lid cooling and 30-minute run','real NVIDIA driver setup/reboot']},indent=2),encoding='utf-8')
    print('Build complete; payload='+str(payload)+'; log='+str(log))
    return 0


if __name__=='__main__':raise SystemExit(main())
