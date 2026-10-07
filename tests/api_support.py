from fastapi.testclient import TestClient as BaseClient
from local_vision_solver.server import create_app as build_app

SECRET = 'test-admin-secret-with-at-least-32-bytes'


def create_app(*args,**kwargs):
    return build_app(*args,**kwargs,admin_secret=SECRET)


class TestClient(BaseClient):
    __test__ = False
    def __init__(self,app,**kwargs):
        port = app.state.jobs.config.server.port
        super().__init__(app,base_url=f'http://127.0.0.1:{port}',
                         client=('127.0.0.1',50000),headers={'Authorization':'Bearer '+SECRET},**kwargs)
