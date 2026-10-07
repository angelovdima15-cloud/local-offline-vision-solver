import hashlib
from pathlib import Path
import httpx
import pytest
from local_vision_solver.app_paths import AppPaths
from local_vision_solver.asset_installer import Asset,AssetInstaller,DownloadPaused,load_manifest


def asset(data):
    return Asset('model','model.gguf','https://example.test/model',len(data),hashlib.sha256(data).hexdigest(),'models/model.gguf',repository_revision='a'*40)


def test_range_resume_and_reuse(tmp_path):
    data=b'model-data'*100;locked=asset(data);requests=[]
    paths=AppPaths.for_user(tmp_path).ensure();(paths.models/'model.gguf.part').write_bytes(data[:123])
    def handle(request):
        requests.append(request)
        assert request.headers['range']=='bytes=123-'
        return httpx.Response(206,headers={'Content-Range':f'bytes 123-{len(data)-1}/{len(data)}'},content=data[123:])
    installer=AssetInstaller(paths,[locked],transport=httpx.MockTransport(handle))
    assert installer.download(locked).read_bytes()==data
    assert installer.download(locked).read_bytes()==data
    assert len(requests)==1


def test_invalid_range_not_published(tmp_path):
    locked=asset(b'abcdef');paths=AppPaths.for_user(tmp_path).ensure();(paths.models/'model.gguf.part').write_bytes(b'ab')
    installer=AssetInstaller(paths,[locked],transport=httpx.MockTransport(lambda req:httpx.Response(206,headers={'Content-Range':'bytes 1-5/6'},content=b'cdef')))
    with pytest.raises(ValueError,match='Content-Range'):installer.download(locked)
    assert not (paths.models/'model.gguf').exists()
    assert (paths.models/'model.gguf.part').read_bytes()==b'ab'


def test_corrupt_asset_not_published(tmp_path):
    locked=asset(b'abcdef');paths=AppPaths.for_user(tmp_path).ensure()
    installer=AssetInstaller(paths,[locked],transport=httpx.MockTransport(lambda req:httpx.Response(200,content=b'ghijkl')))
    with pytest.raises(ValueError,match='partial_corrupt'):installer.download(locked)
    assert not (paths.models/'model.gguf').exists()
    assert (paths.models/'model.gguf.part').exists()
    installer.restart_download('model')
    assert not (paths.models/'model.gguf.part').exists()


def test_pause_preserves_partial(tmp_path):
    locked=asset(b'abcdef');paths=AppPaths.for_user(tmp_path).ensure();partial=paths.models/'model.gguf.part';partial.write_bytes(b'ab')
    installer=AssetInstaller(paths,[locked]);installer.pause.set()
    with pytest.raises(DownloadPaused):installer.download(locked)
    assert partial.read_bytes()==b'ab'


def test_manifest_pins_revision_and_sizes():
    assets=load_manifest()
    assert len(assets)==4
    assert all('/resolve/main/' not in a.download_url and a.size_bytes>0 for a in assets)

