"""Resumable, pinned initial setup. This module never selects a floating model revision."""
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import shutil
import threading
import time
from uuid import uuid4
import zipfile
import httpx
from .app_paths import AppPaths
from .image_policy import check_disk
from .job_service import file_hash
from .storage import write_json


class DownloadPaused(RuntimeError):
    pass


@dataclass(frozen=True)
class Asset:
    asset_id: str
    filename: str
    download_url: str
    size_bytes: int
    sha256: str
    destination: str
    version: str | None = None
    repository_revision: str | None = None

    def validate(self):
        if (Path(self.filename).name != self.filename or '\\' in self.filename
                or Path(self.destination).is_absolute() or '..' in Path(self.destination).parts
                or not self.download_url.startswith('https://') or '/resolve/main/' in self.download_url
                or self.size_bytes <= 0 or not re.fullmatch('[0-9a-f]{64}',self.sha256)):
            raise ValueError('Invalid pinned asset')
        return self


def load_manifest(path=None):
    path = path or Path(__file__).with_name('assets.lock.json')
    value = json.loads(path.read_text(encoding='utf-8'))
    if value['schema_version'] != 1:
        raise ValueError('Unsupported assets manifest')
    assets = [Asset(**record).validate() for record in value['assets']]
    if len({a.destination for a in assets}) != len(assets):
        raise ValueError('Duplicate asset destination')
    return assets


class AssetInstaller:
    def __init__(self,paths:AppPaths,assets=None,progress=None,transport=None):
        self.paths = paths.ensure()
        self.assets = assets if assets is not None else load_manifest()
        self.progress = progress or (lambda value:None)
        self.pause = threading.Event()
        self.transport = transport

    def report(self,stage,asset,received=0,speed=0):
        self.progress({'stage':stage,'asset_id':asset.asset_id,'bytes':received,'total':asset.size_bytes,
                       'speed':speed,'eta':(asset.size_bytes-received)/speed if speed else None})

    def target(self,asset):
        target = (self.paths.data/asset.destination).resolve()
        if not target.is_relative_to(self.paths.data) or target.name != asset.filename:
            raise ValueError('Unsafe asset destination')
        return target

    @staticmethod
    def valid(path,asset):
        return path.is_file() and path.stat().st_size == asset.size_bytes and file_hash(path)==asset.sha256

    def restart_download(self,asset_id):
        asset = next(a for a in self.assets if a.asset_id==asset_id)
        target=self.target(asset)
        partial = target.with_name(asset.filename+'.part')
        partial.unlink(missing_ok=True)
        if target.exists() and not self.valid(target,asset):target.unlink()

    def download(self,asset):
        target = self.target(asset)
        target.parent.mkdir(parents=True,exist_ok=True)
        if target.exists():
            self.report('verifying',asset,target.stat().st_size)
            if self.valid(target,asset):
                return target
            raise ValueError('asset_corrupt: '+asset.asset_id)
        partial = target.with_name(target.name+'.part')
        if partial.is_file() and partial.stat().st_size==asset.size_bytes:
            if not self.valid(partial,asset):
                raise ValueError('partial_corrupt: '+asset.asset_id)
            partial.replace(target)
            return target
        with httpx.Client(timeout=httpx.Timeout(connect=15,read=60,write=60,pool=15),
                          follow_redirects=True,trust_env=False,transport=self.transport) as client:
            for attempt in range(4):
                if self.pause.is_set():
                    raise DownloadPaused('Download paused; partial retained')
                received = partial.stat().st_size if partial.exists() else 0
                check_disk(target.parent,max(0,asset.size_bytes-received))
                headers = {'Range':f'bytes={received}-'} if received else {}
                headers['Accept-Encoding']='identity'
                try:
                    with client.stream('GET',asset.download_url,headers=headers) as response:
                        response.raise_for_status()
                        append = response.status_code==206
                        if append:
                            match = re.fullmatch(r'bytes (\d+)-(\d+)/(\d+)',response.headers.get('Content-Range',''))
                            if (not match or int(match[1])!=received or int(match[3])!=asset.size_bytes
                                    or int(match[2])!=asset.size_bytes-1):
                                raise ValueError('Invalid Content-Range')
                        elif response.status_code==200:
                            received=0
                        else:
                            raise ValueError('Unexpected download response')
                        started,initial = time.monotonic(),received
                        with partial.open('ab' if append else 'wb') as handle:
                            for chunk in response.iter_bytes(4*1024**2):
                                if self.pause.is_set():
                                    raise DownloadPaused('Download paused; partial retained')
                                if received+len(chunk)>asset.size_bytes:
                                    raise ValueError('Asset larger than locked size')
                                handle.write(chunk)
                                received+=len(chunk)
                                self.report('downloading',asset,received,(received-initial)/max(.001,time.monotonic()-started))
                            handle.flush()
                            os.fsync(handle.fileno())
                    if received != asset.size_bytes:
                        raise httpx.ReadError('Download incomplete')
                    self.report('verifying',asset,received)
                    if not self.valid(partial,asset):
                        raise ValueError('partial_corrupt: '+asset.asset_id)
                    partial.replace(target)
                    return target
                except (httpx.HTTPError,OSError):
                    if attempt==3:
                        raise
                    if self.pause.wait((2,5,15)[attempt]):
                        raise DownloadPaused('Download paused; partial retained')

    def install(self,*,runtime_only=False,models_only=False):
        state_path = self.paths.data/'install-state.json'
        for asset in self.assets:
            if runtime_only and not asset.filename.endswith('.zip'):
                continue
            if models_only and asset.filename.endswith('.zip'):
                continue
            write_json(state_path,{'state':'installing','asset_id':asset.asset_id})
            self.download(asset)
        if not models_only:
            self.publish_runtime()
        write_json(self.paths.data/'assets.lock.json',{'schema_version':1,'assets':[a.__dict__ for a in self.assets]})
        write_json(state_path,{'state':'complete'})

    def publish_runtime(self):
        record_path = self.paths.data/'runtime-files.json'
        if record_path.exists():
            record = json.loads(record_path.read_text(encoding='utf-8'))
            if record.get('archives')!={a.asset_id:a.sha256 for a in self.assets if a.filename.endswith('.zip')}:
                raise RuntimeError('runtime_profile_change_requires_explicit_update')
            if record.get('archives')=={a.asset_id:a.sha256 for a in self.assets if a.filename.endswith('.zip')}:
                if all((self.paths.runtime/name).is_file() and file_hash(self.paths.runtime/name)==sha for name,sha in record['files'].items()):
                    return
        staging = self.paths.runtime.parent/('staging-'+uuid4().hex)
        staging.mkdir()
        try:
            names = set()
            for asset in self.assets:
                if not asset.filename.endswith('.zip'):
                    continue
                with zipfile.ZipFile(self.target(asset)) as archive:
                    if sum(i.file_size for i in archive.infolist())>2*1024**3:
                        raise ValueError('Runtime expansion limit')
                    for item in archive.infolist():
                        name = Path(item.filename).name
                        if item.is_dir() or Path(name).suffix.lower() not in {'.dll','.exe'}:
                            continue
                        if name.lower() in names or '\\' in name or '/' in name:
                            raise ValueError('Duplicate or unsafe runtime file')
                        names.add(name.lower())
                        with archive.open(item) as source,(staging/name).open('wb') as output:
                            shutil.copyfileobj(source,output,4*1024**2)
            if not (staging/'llama-server.exe').is_file():
                raise ValueError('Missing llama-server.exe')
            hashes = {p.name:file_hash(p) for p in staging.iterdir()}
            old = self.paths.runtime.parent/('previous-'+uuid4().hex)
            if self.paths.runtime.exists():
                self.paths.runtime.replace(old)
            try:
                staging.replace(self.paths.runtime)
            except BaseException:
                if old.exists():
                    old.replace(self.paths.runtime)
                raise
            if old.exists():
                shutil.rmtree(old)
            write_json(record_path,{'files':hashes,'archives':{a.asset_id:a.sha256 for a in self.assets if a.filename.endswith('.zip')}})
        finally:
            if staging.exists():
                shutil.rmtree(staging)
