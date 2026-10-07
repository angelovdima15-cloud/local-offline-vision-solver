import time
import threading
from uuid import uuid4
import pytest
from api_support import TestClient, create_app
from test_api import config, photo, create, submit, wait
from local_vision_solver.job_repository import JobRepository, StorageUnavailable
from local_vision_solver.server import JobManager, SubmitTask, demo_runner


def fail(*args,**kwargs):
    raise StorageUnavailable('injected disk failure')


def test_submit_storage_failure_does_not_create_phantom_queue(config,monkeypatch):
    app = create_app(config,demo=True)
    with TestClient(app) as client:
        identifier = create(client)
        client.put(f'/v1/sessions/{identifier}/pages/1',content=photo())
        original = app.state.jobs.repository.submit
        monkeypatch.setattr(app.state.jobs.repository,'submit',fail)
        assert submit(client,identifier).status_code==503
        monkeypatch.setattr(app.state.jobs.repository,'submit',original)
        assert app.state.jobs.repository.get(identifier)['state']=='RECEIVING'


def test_create_storage_failure_is_recoverable(config,monkeypatch):
    app=create_app(config,demo=True)
    with TestClient(app) as client:
        original=app.state.jobs.repository.create
        monkeypatch.setattr(app.state.jobs.repository,'create',fail)
        identifier=str(uuid4())
        assert client.post('/v1/sessions',json={'session_id':identifier}).status_code==503
        assert identifier not in app.state.jobs.jobs
        monkeypatch.setattr(app.state.jobs.repository,'create',original)
        app.state.jobs.storage_ok=True
        assert create(client,identifier)==identifier


@pytest.mark.parametrize('target',['event','cleanup'])
def test_worker_survives_auxiliary_failure(config,monkeypatch,target):
    app=create_app(config,demo=True)
    with TestClient(app) as client:
        identifier=create(client)
        if target=='event':
            monkeypatch.setattr('local_vision_solver.storage.Session.event',lambda *a,**k: (_ for _ in ()).throw(OSError('log failed')))
        else:
            monkeypatch.setattr(app.state.jobs,'_cleanup_expired',lambda: (_ for _ in ()).throw(OSError('cleanup failed')))
        assert client.put(f'/v1/sessions/{identifier}/pages/1',content=photo()).status_code==200
        assert submit(client,identifier).status_code==202
        assert wait(client,identifier)['state']=='COMPLETE'
        assert app.state.jobs.worker.is_alive()


def test_worker_readiness_reports_failure(config):
    app=create_app(config,demo=True)
    with TestClient(app) as client:
        app.state.jobs.worker_error='worker_failed'
        assert client.get('/ready').status_code==503
        assert client.get('/health').json()['worker']['error']=='worker_failed'


def test_expired_receiving_sessions_do_not_block_creation(config):
    app=create_app(config,demo=True)
    with TestClient(app) as client:
        for _ in range(32):
            job=app.state.jobs.create()
            app.state.jobs.repository.update(job.session.id,updated_at=time.time()-3700)
        assert client.post('/v1/sessions',json={}).status_code==201


def test_queued_jobs_survive_restart(config):
    manager=JobManager(config,demo_runner(config),demo=True)
    manager.start()
    job=manager.create()
    manager.model_ready=False
    from local_vision_solver.image_policy import ImagePolicy
    path=job.session.path/'incoming'/'page_01.jpg';path.write_bytes(photo())
    from local_vision_solver.job_service import file_hash
    manager.repository.add_page(job.session.id,dict(ImagePolicy().inspect(path),number=1,file=path.name,bytes=path.stat().st_size,sha256=file_hash(path)),300*1024**2)
    manager.repository.submit(job.session.id,[1],8)
    manager.close()
    with TestClient(create_app(config,demo=True)) as client:
        assert wait(client,job.session.id)['state']=='COMPLETE'


def test_corrupted_complete_result_is_not_reported_ready(config):
    with TestClient(create_app(config,demo=True)) as client:
        identifier=create(client);client.put(f'/v1/sessions/{identifier}/pages/1',content=photo());submit(client,identifier)
        assert wait(client,identifier)['state']=='COMPLETE'
    (config.pipeline.session_directory/identifier/'result.json').write_text('{}',encoding='utf-8')
    with TestClient(create_app(config,demo=True)) as client:
        value=client.get(f'/v1/sessions/{identifier}').json()
        assert value['state']=='ERROR' and not value['result_available']


def test_cleanup_does_not_remove_active_download(config):
    app=create_app(config,demo=True)
    with TestClient(app) as client:
        identifier=create(client);job=app.state.jobs.get(identifier)
        app.state.jobs.repository.update(identifier,updated_at=time.time()-3700)
        with app.state.jobs.lease(job):
            app.state.jobs._cleanup_expired()
            assert job.session.path.exists()
            assert client.delete(f'/v1/sessions/{identifier}').status_code==409
        app.state.jobs._cleanup_expired()
        assert client.get(f'/v1/sessions/{identifier}').status_code==404


def test_render_failure_and_retry_preserves_text_without_model(config,monkeypatch):
    import local_vision_solver.job_service as service
    original=service.CardRenderer.render
    calls=[]
    run=demo_runner(config)
    def tracked(paths,session):
        calls.append(session.id)
        return run(paths,session)
    monkeypatch.setattr(service.CardRenderer,'render',lambda *a: (_ for _ in ()).throw(OSError('disk full')))
    app=create_app(config,runner=tracked,demo=True)
    with TestClient(app) as client:
        identifier=create(client);client.put(f'/v1/sessions/{identifier}/pages/1',content=photo());submit(client,identifier)
        deadline=time.monotonic()+5
        while time.monotonic()<deadline:
            value=client.get(f'/v1/sessions/{identifier}').json()
            if value['output_error']:break
            time.sleep(.02)
        assert value['state']=='ANSWER_READY' and value['answer_available']
        assert client.get(f'/v1/sessions/{identifier}/answer.txt').status_code==200
        assert client.get(f'/v1/sessions/{identifier}/package').status_code==425
        monkeypatch.setattr(service.CardRenderer,'render',original)
        assert client.post(f'/v1/sessions/{identifier}/render').status_code==202
        assert wait(client,identifier)['state']=='COMPLETE'
        assert calls==[identifier]


def test_sqlite_transaction_rolls_back(tmp_path):
    repo=JobRepository(tmp_path/'state.sqlite3');repo.initialize()
    with pytest.raises(StorageUnavailable):
        with repo.connection() as db:
            db.execute("INSERT INTO sessions(id,owner_client_id,created_at,updated_at,state) VALUES('one','admin',1,1,'QUEUED')")
            db.execute('INSERT INTO nonexistent VALUES(1)')
    assert repo.all()==[]


def test_legacy_complete_import_preserves_metadata_and_verified_text(config):
    import json
    import shutil
    from local_vision_solver.job_service import finalize_outputs
    from local_vision_solver.storage import Session,write_json
    session=Session(config.pipeline.session_directory)
    (session.path/'incoming').mkdir()
    answer=demo_runner(config)([],session)
    finalize_outputs(config,session,answer,time.time())
    write_json(session.path/'verified_answer.json',answer.draft.model_dump())
    write_json(session.path/'job.json',{'session_id':session.id,'created_at':time.time(),'state':'COMPLETE','pages':{},'page_order':[],'error':None})
    with TestClient(create_app(config,demo=True)) as client:
        value=client.get('/v1/sessions/'+session.id).json()
        assert value['state']=='COMPLETE' and value['answer_available']
        assert client.get('/v1/sessions/'+session.id+'/answer.txt').status_code==200
        assert (session.path/'job.json').exists()
