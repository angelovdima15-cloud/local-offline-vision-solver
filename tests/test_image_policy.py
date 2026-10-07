from io import BytesIO
import pytest
from PIL import Image
from local_vision_solver.image_policy import ImagePolicy
from api_support import TestClient,create_app
from test_api import config,photo,create


def test_pixel_limit_precedes_decode(monkeypatch):
    data=BytesIO();Image.new('RGB',(2000,2000)).save(data,format='PNG');data.seek(0)
    monkeypatch.setattr(Image.Image,'load',lambda self:pytest.fail('full decode before pixel check'))
    with pytest.raises(ValueError,match='image_pixel_limit'):
        ImagePolicy(max_pixels=1_000_000).inspect(data)


def test_multi_frame_rejected():
    data=BytesIO();Image.new('RGB',(200,200)).save(data,format='TIFF',save_all=True,append_images=[Image.new('RGB',(200,200))]);data.seek(0)
    with pytest.raises(ValueError,match='single-frame'):
        ImagePolicy().inspect(data)


def test_page_commit_failure_never_acknowledged(config,monkeypatch):
    from local_vision_solver.job_repository import StorageUnavailable
    app=create_app(config,demo=True)
    with TestClient(app) as client:
        identifier=create(client)
        monkeypatch.setattr(app.state.jobs.repository,'add_page',lambda *a: (_ for _ in ()).throw(StorageUnavailable('disk full')))
        assert client.put(f'/v1/sessions/{identifier}/pages/1',content=photo()).status_code==503
        assert app.state.jobs.repository.get(identifier)['pages']=={}

