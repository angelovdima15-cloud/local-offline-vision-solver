from fastapi.testclient import TestClient as PublicClient
from api_support import TestClient,create_app
from test_api import config,photo,create


def phone(app):
    return PublicClient(app,base_url='http://127.0.0.1:8765',client=('192.168.1.2',1234))


def test_unauthorized_rejected_before_upload_and_known_uuid(config):
    app=create_app(config,demo=True)
    with TestClient(app) as admin:
        identifier=create(admin)
        client=phone(app)
        for method,path in [('post','/v1/sessions'),('post','/preview'),('put',f'/v1/sessions/{identifier}/pages/1'),('get',f'/v1/sessions/{identifier}')]:
            assert getattr(client,method)(path).status_code==401


def test_pairing_single_use_cookie_and_owner_isolation(config):
    app=create_app(config,demo=True)
    with TestClient(app) as admin:
        token=admin.post('/v1/admin/pairing').json()['token']
        client=phone(app)
        response=client.post('/v1/pairing/exchange',json={'token':token})
        assert response.status_code==200
        assert 'HttpOnly' in response.headers['set-cookie'] and 'SameSite=strict' in response.headers['set-cookie']
        assert client.post('/v1/pairing/exchange',json={'token':token}).status_code==401
        identifier=create(client)
        other=phone(app)
        second=admin.post('/v1/admin/pairing').json()['token']
        assert other.post('/v1/pairing/exchange',json={'token':second}).status_code==200
        assert other.get(f'/v1/sessions/{identifier}').status_code==404
        assert other.delete(f'/v1/sessions/{identifier}').status_code==404
        assert client.get('/v1/admin/clients').status_code==403
        owner=response.json()['client_id']
        assert admin.delete('/v1/admin/clients/'+owner).status_code==204
        assert client.get(f'/v1/sessions/{identifier}').status_code==401


def test_expired_pairing(config):
    from local_vision_solver.security import digest
    app=create_app(config,demo=True)
    with TestClient(app) as admin:
        token=admin.post('/v1/admin/pairing').json()['token']
        app.state.security.tokens[digest(token)]=0
        assert phone(app).post('/v1/pairing/exchange',json={'token':token}).status_code==401


def test_host_origin_and_remote_admin_are_rejected(config):
    app=create_app(config,demo=True)
    with TestClient(app) as admin:
        assert admin.get('/health',headers={'Host':'attacker.example:8765'}).status_code==400
        assert admin.get('/health',headers={'Host':'127.0.0.1:9999'}).status_code==400
        assert admin.post('/v1/sessions',json={},headers={'Origin':'http://attacker.example:8765','Host':'attacker.example:8765'}).status_code==400
        remote=phone(app)
        remote.headers.update(admin.headers)
        assert remote.post('/v1/admin/pairing').status_code==401
