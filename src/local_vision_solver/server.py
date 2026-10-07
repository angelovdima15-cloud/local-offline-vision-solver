"""Durable authenticated local API; only the job service publishes COMPLETE."""
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass, field
import asyncio
from io import BytesIO
import json
import logging
from pathlib import Path
import shutil
import threading
import time
from uuid import UUID, uuid4
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import Field

from .config import Config, StrictModel
from .discovery import Advertisement, lan_addresses
from .image_service import ImageService
from .job_repository import JobRepository, StorageUnavailable, RepositoryConflict, RepositoryLimit
from .job_service import save_answer, load_answer, finalize_outputs, validate_outputs, file_hash
from .models import Block, Draft, VerifiedAnswer
from .pipeline import Pipeline, PipelineError
from .security import Security, COOKIE, allowed_authority
from .storage import Session, write_json

logger = logging.getLogger("vision.service")
BUSY = {"QUEUED", "RUNNING", "RENDERING", "PACKAGING"}


class CreateSession(StrictModel):
    session_id: UUID | None = None


class SubmitTask(StrictModel):
    page_count: int = Field(ge=1, le=100)
    page_order: list[int] = Field(min_length=1, max_length=100)


class Exchange(StrictModel):
    token: str = Field(min_length=1, max_length=128)
    name: str = Field(default="iPhone", max_length=80)


@dataclass
class Job:
    session: Session
    created_at: float
    state: str = "RECEIVING"
    pages: dict = field(default_factory=dict)
    order: list = field(default_factory=list)
    error: dict | None = None
    owner: str = "admin"
    updated_at: float = 0
    stage: str | None = None
    output_error: dict | None = None
    verified_hash: str | None = None
    upload_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    references: int = 0


class JobManager:
    def __init__(self, config: Config, runner=None, *, demo=False):
        self.config, self.demo = config, demo
        self.runner = runner or (lambda paths, session: Pipeline(config).verify(paths, session=session)[1])
        self.repository = JobRepository(config.paths.database)
        self.jobs = {}
        self.guard = threading.RLock()
        self.stop = threading.Event()
        self.wake = threading.Event()
        self.worker = threading.Thread(target=self._work, name="vision-gpu-worker", daemon=True)
        self.storage_ok = False
        self.worker_error = None
        self.model_ready = True  # The owning supervisor disables admission when runtime fails.

    def _event(self, job, state, **details):
        try:
            job.session.event(state, **details)
        except StorageUnavailable:
            raise
        except Exception:
            logger.error("Event log failed for %s", job.session.id, exc_info=True)

    def _hydrate(self, record):
        with self.guard:
            job = self.jobs.get(record['id'])
            if job is None:
                session = Session(self.config.pipeline.session_directory, record['id'], restore=True)
                job = Job(session, record['created_at'])
                self.jobs[record['id']] = job
            job.state, job.pages, job.order = record['state'], record['pages'], record['page_order']
            job.owner, job.updated_at, job.stage = record['owner_client_id'], record['updated_at'], record['stage']
            job.verified_hash = record['verified_answer_sha256']
            job.error = ({'code':record['error_code'], 'message':record['error_message']} if record['error_code'] else None)
            job.output_error = ({'code':record['output_error_code'], 'message':record['output_error_message']} if record['output_error_code'] else None)
            return job

    def _recover(self):
        root = self.config.pipeline.session_directory
        for metadata in root.glob('*/job.json'):
            try:
                identifier = str(UUID(metadata.parent.name))
                if self.repository.get(identifier):
                    continue
                data = json.loads(metadata.read_text(encoding='utf-8'))
                if data['session_id'] != identifier:
                    raise ValueError('Legacy UUID mismatch')
                self.repository.create(identifier, data.get('owner_client_id','admin'), self.demo,
                                       limit=100000, created_at=data['created_at'])
                for number, page in data['pages'].items():
                    name = page['file']
                    if Path(name).name != name or '\\' in name:
                        raise ValueError('Unsafe legacy filename')
                    path = metadata.parent / 'incoming' / name
                    if file_hash(path) != page['sha256'] or path.stat().st_size != page['bytes']:
                        raise ValueError('Legacy page integrity mismatch')
                    from .image_policy import ImagePolicy, DECODE_LOCK
                    with DECODE_LOCK:
                        info = ImagePolicy(self.config.server.max_image_pixels).inspect(path)
                    self.repository.add_page(identifier, dict(page, number=int(number), **info), self.config.pipeline.max_input_megabytes*1024**2)
                if data['state'] == 'QUEUED':
                    self.repository.submit(identifier,data['page_order'],100000)
                else:
                    self.repository.update(identifier,state=data['state'],page_order=data['page_order'])
                if data['state']=='COMPLETE':
                    session=Session(root,identifier,restore=True)
                    value=json.loads((session.path/'result.json').read_text(encoding='utf-8'))
                    if not (session.path/'result.zip').is_file():
                        from .package import build_package
                        build_package(value,session.path,data['created_at'],demo=value.get('demo',False))
                    validate_outputs(session)
                    raw=json.loads((session.path/'verified_answer.json').read_text(encoding='utf-8'))
                    if 'draft' not in raw:
                        answer=VerifiedAnswer(session_id=identifier,draft=Draft.model_validate(raw),metadata=value,demo=value.get('demo',False))
                    else:answer=VerifiedAnswer.model_validate(raw)
                    sha=save_answer(session,answer)
                    self.repository.update(identifier,verified_answer_sha256=sha,result_sha256=file_hash(session.path/'result.json'),package_sha256=file_hash(session.path/'result.zip'))
            except StorageUnavailable:
                raise
            except Exception as exc:
                self.config.paths.recovery.mkdir(parents=True,exist_ok=True)
                write_json(self.config.paths.recovery / (metadata.parent.name + '.json'),
                           {'source':str(metadata), 'error':str(exc)})
                try:
                    if self.repository.get(metadata.parent.name):
                        self.repository.update(metadata.parent.name,state='ERROR',error_code='recovery_failed',error_message=str(exc))
                except ValueError:
                    pass
                logger.error('Legacy recovery failed in %s',metadata.parent.name,exc_info=True)
        for record in self.repository.all():
            try:
                job = self._hydrate(record)
                if job.state == 'RUNNING':
                    self.repository.update(job.session.id,state='ERROR',error_code='interrupted',error_message='????????? ????????. ????????? ??????????? ???? ??????.')
                elif job.state in {'RENDERING','PACKAGING'}:
                    load_answer(job.session,job.verified_hash)
                    self.repository.update(job.session.id,state='ANSWER_READY',output_error_code='interrupted',output_error_message='?????????? ?????? ????????. ????????? ??.')
                elif job.state == 'COMPLETE':
                    validate_outputs(job.session,record['result_sha256'],record['package_sha256'])
                elif job.state == 'ANSWER_READY':
                    load_answer(job.session,job.verified_hash)
            except Exception as exc:
                if isinstance(exc,StorageUnavailable):
                    raise
                self.repository.update(record['id'],state='ERROR',error_code='result_corrupt',error_message='??????????? ????? ??????????: ' + str(exc))
                logger.error('Stored session %s is invalid',record['id'],exc_info=True)

    def start(self):
        try:
            self.config.paths.ensure()
            self.config.pipeline.session_directory.mkdir(parents=True,exist_ok=True)
            self.repository.initialize()
            self._recover()
            self.storage_ok = True
            self._safe_cleanup()
        except (StorageUnavailable, OSError):
            self.storage_ok = False
            self.worker_error = 'storage_unavailable'
            logger.error('Storage startup failed',exc_info=True)
        self.worker.start()
        self.wake.set()

    def close(self):
        self.stop.set()
        self.wake.set()
        if self.worker.is_alive():
            self.worker.join(timeout=2)

    def available(self):
        if not self.storage_ok:
            raise HTTPException(503,'storage_unavailable')
        if not self.worker.is_alive() or self.worker_error:
            raise HTTPException(503,'worker_unavailable')
        if not self.model_ready:
            raise HTTPException(503,'model_unavailable')

    def create(self, identifier=None, owner='admin'):
        self.available()
        self._safe_cleanup()
        identifier = str(UUID(str(identifier))) if identifier else str(uuid4())
        existing = self.repository.get(identifier)
        if existing:
            job = self._hydrate(existing)
            self.authorize(job,owner)
            return job
        session = None
        try:
            target = self.config.pipeline.session_directory / identifier
            # A failed create may leave an empty directory; never overwrite any data.
            if target.is_dir() and not self.repository.get(identifier):
                if any((target/'incoming').glob('*')) if (target/'incoming').exists() else False:
                    raise HTTPException(409,'orphaned_session')
                session = Session(self.config.pipeline.session_directory,identifier,restore=True)
            else:
                session = Session(self.config.pipeline.session_directory,identifier)
            (session.path/'incoming').mkdir(exist_ok=True)
            record = self.repository.create(identifier,owner,self.demo,self.config.server.max_active_sessions)
            return self._hydrate(record)
        except RepositoryLimit as exc:
            if session and not any((session.path/'incoming').iterdir()):
                shutil.rmtree(session.path)
            raise HTTPException(429,str(exc)) from exc
        except (StorageUnavailable,OSError) as exc:
            if session:
                try:
                    if not self.repository.get(identifier) and not any((session.path/'incoming').iterdir()):
                        shutil.rmtree(session.path)
                except (OSError,StorageUnavailable):
                    pass
            raise StorageUnavailable('Cannot create session') from exc

    @staticmethod
    def authorize(job,owner):
        if owner != 'admin' and job.owner != owner:
            raise HTTPException(404,'Session not found')

    def get(self, identifier, owner='admin'):
        record = self.repository.get(str(identifier))
        if record is None:
            raise HTTPException(404,'Session not found')
        job = self._hydrate(record)
        self.authorize(job,owner)
        return job

    def submit(self,job,task):
        self.available()
        self._safe_cleanup()
        if task.page_count > self.config.pipeline.max_pages or sorted(task.page_order) != list(range(1,task.page_count+1)):
            raise HTTPException(422,'Page order must include every page exactly once')
        try:
            self.repository.submit(job.session.id,task.page_order,self.config.server.max_queued_jobs)
        except RepositoryConflict as exc:
            raise HTTPException(422 if str(exc)=='missing_pages' else 409,str(exc)) from exc
        except RepositoryLimit as exc:
            raise HTTPException(429,str(exc),headers={'Retry-After':'3'}) from exc
        self.wake.set()
        self._event(job,'QUEUED')

    def status(self,job):
        job = self.get(job.session.id)
        stage = job.stage
        if job.state == 'RUNNING':
            try:
                stage = json.loads((job.session.path/'status.json').read_text(encoding='utf-8'))['state']
            except (OSError,ValueError,KeyError):
                pass
        answer = job.state in {'ANSWER_READY','RENDERING','PACKAGING','COMPLETE'} and bool(job.verified_hash)
        return {'session_id':job.session.id,'created_at':job.created_at,'updated_at':job.updated_at,
                'state':job.state,'stage':stage,'page_count':len(job.pages),'page_order':job.order,
                'answer_available':answer,'cards_available':job.state=='COMPLETE',
                'result_available':job.state=='COMPLETE','error':job.error,'output_error':job.output_error,'demo':self.demo}

    def transition(self,job,state,**values):
        self.repository.update(job.session.id,state=state,**values)
        self._event(job,state)

    def _process(self,record):
        job = self._hydrate(record)
        identifier = job.session.id
        lifecycle={'RECEIVING','QUEUED','RUNNING','ANSWER_READY','RENDERING','PACKAGING','COMPLETE','ERROR'}
        job.session.on_stage=lambda stage:self.repository.update(identifier,stage=stage) if stage not in lifecycle else None
        if record['render_only']:
            answer = load_answer(job.session,job.verified_hash)
        else:
            paths = [job.session.path/'incoming'/job.pages[i]['file'] for i in job.order]
            for number,path in zip(job.order,paths):
                page=job.pages[number]
                if path.stat().st_size!=page['bytes'] or file_hash(path)!=page['sha256']:
                    raise PipelineError('Файл принятой страницы повреждён. Отправьте оригиналы заново.',job.session,'page_corrupt')
            answer = self.runner(paths,job.session)
            if self.repository.get(identifier)['state'] != 'RUNNING':
                raise PipelineError('Model context was interrupted',job.session,'model_crash')
            if not isinstance(answer,VerifiedAnswer) or answer.session_id != identifier:
                raise ValueError('Pipeline must return a typed verified answer for this session')
            answer.demo = self.demo
            sha = save_answer(job.session,answer)
            self.transition(job,'ANSWER_READY',verified_answer_sha256=sha,stage=None)
        try:
            finalize_outputs(self.config,job.session,answer,job.created_at,lambda state:self.transition(job,state))
            self.transition(job,'COMPLETE',completed_at=time.time(),output_error_code=None,output_error_message=None,
                            result_sha256=file_hash(job.session.path/'result.json'),package_sha256=file_hash(job.session.path/'result.zip'))
        except StorageUnavailable:
            raise
        except Exception as exc:
            phase=self.repository.get(identifier)['state']
            self.transition(job,'ANSWER_READY',output_error_code='package_failed' if phase=='PACKAGING' else 'render_failed',output_error_message=str(exc))
            logger.error('Output failed for %s; verified text retained',identifier,exc_info=True)

    def _work(self):
        next_cleanup = 0
        while not self.stop.is_set():
            record = None
            try:
                if not self.storage_ok:
                    self.wake.wait(5)
                    self.wake.clear()
                    try:
                        self.repository.initialize()
                        self._recover()
                        self.storage_ok = True
                        self.worker_error = None
                    except (StorageUnavailable,OSError):
                        continue
                if time.monotonic() >= next_cleanup:
                    self._safe_cleanup()
                    next_cleanup = time.monotonic()+self.config.server.cleanup_interval_seconds
                record = self.repository.claim() if self.model_ready else None
                if record:
                    self._process(record)
                else:
                    self.wake.wait(1)
                    self.wake.clear()
            except StorageUnavailable:
                self.storage_ok = False
                self.worker_error = 'storage_unavailable'
                logger.error('Worker storage failure',exc_info=True)
            except Exception as exc:
                logger.error('Worker operation failed',exc_info=True)
                if record:
                    try:
                        self.repository.update(record['id'],state='ERROR',error_code=getattr(exc,'code','processing_failed'),error_message=str(exc))
                    except StorageUnavailable:
                        self.storage_ok = False
                        self.worker_error = 'storage_unavailable'
                else:
                    self.worker_error = 'worker_failed'
                    self.stop.wait(1)

    @contextmanager
    def lease(self,job):
        with self.guard:
            if self.repository.get(job.session.id) is None:
                raise HTTPException(404,'Session not found')
            job.references += 1
        try:
            yield
        finally:
            with self.guard:
                job.references -= 1

    def delete(self,job):
        with self.guard:
            job = self.get(job.session.id)
            if job.state in BUSY or job.upload_lock.locked() or job.references:
                raise HTTPException(409,'session_in_use')
            self._remove(job)

    def _remove(self,job):
        root = self.config.pipeline.session_directory.resolve()
        target = job.session.path.resolve()
        if target.parent != root or target.name != job.session.id:
            raise ValueError('Invalid session removal path')
        if target.exists():
            shutil.rmtree(target)
        self.repository.delete(job.session.id)
        self.jobs.pop(job.session.id,None)

    def _cleanup_expired(self):
        now = time.time()
        for record in self.repository.all():
            receiving = record['state']=='RECEIVING' and record['updated_at'] < now-self.config.server.receiving_idle_timeout_seconds
            completed = not self.config.server.retain_sessions and record['state'] in {'COMPLETE','ERROR','ANSWER_READY'} and record['updated_at'] < now-self.config.server.retention_hours*3600
            if receiving or completed:
                with self.guard:
                    job = self._hydrate(record)
                    if not job.references and not job.upload_lock.locked():
                        try:
                            self._remove(job)
                        except OSError:
                            logger.error('Cleanup failed for %s; will retry',job.session.id,exc_info=True)

    def _safe_cleanup(self):
        try:
            self._cleanup_expired()
        except Exception:
            logger.error('Periodic cleanup failed; worker remains alive',exc_info=True)


class LeasedFileResponse(FileResponse):
    def __init__(self,manager,job,*args,**kwargs):
        self.manager,self.job = manager,job
        with manager.guard:
            if manager.repository.get(job.session.id) is None:
                raise HTTPException(404,'Session not found')
            job.references += 1
        super().__init__(*args,**kwargs)

    async def __call__(self,scope,receive,send):
        try:
            await super().__call__(scope,receive,send)
        finally:
            with self.manager.guard:
                self.job.references -= 1


def demo_runner(config):
    def run(paths,session):
        draft = Draft(detected_language='en',answered_question_ids=['transport_demo'],final_answer=[],
                      solution=[Block(kind='text',content='TRANSPORT DEMO\n\nNo AI solution was generated.\n\nReceived '+str(len(paths))+' page(s).')],
                      numeric_checks=[],warnings=['Transport test only'],confidence=0)
        return VerifiedAnswer(session_id=session.id,draft=draft,demo=True,
                              metadata={'subject':'mixed','task_type':'transport_demo','problem_text':'Not read in demo mode','warnings':['TRANSPORT DEMO: not an academic answer']})
    return run


def create_app(config:Config,*,runner=None,demo=False,advertise=None,open_browser=False,admin_secret=None):
    manager = JobManager(config,runner or (demo_runner(config) if demo else None),demo=demo)
    security = Security(manager.repository,admin_secret)
    images = ImageService(config)

    def connection_urls():
        if config.server.host in {'127.0.0.1','localhost','::1'}:
            return []
        return [f'http://{ip}:{config.server.port}/' for ip in lan_addresses()]

    @asynccontextmanager
    async def lifespan(app):
        await asyncio.to_thread(manager.start)
        advertisement = None
        if config.server.advertise if advertise is None else advertise:
            try:
                advertisement = await asyncio.to_thread(Advertisement,config.server)
            except Exception:
                logger.warning('Bonjour unavailable',exc_info=True)
        try:
            if open_browser:
                import webbrowser
                token=security.pairing()
                async def open_later():
                    await asyncio.sleep(1)
                    await asyncio.to_thread(webbrowser.open,f'http://127.0.0.1:{config.server.port}/#pair={token}')
                asyncio.create_task(open_later())
            yield
        finally:
            if advertisement:
                await asyncio.to_thread(advertisement.close)
            await asyncio.to_thread(manager.close)

    app = FastAPI(title='Vision',version='0.4.0',lifespan=lifespan,docs_url=None,redoc_url=None,openapi_url=None)
    app.state.jobs,app.state.security = manager,security
    app.state.images = images

    @app.exception_handler(StorageUnavailable)
    async def storage_failure(request,exc):
        manager.storage_ok = False
        return JSONResponse({'detail':'storage_unavailable'},status_code=503)

    @app.middleware('http')
    async def policy(request,call_next):
        addresses = lan_addresses()
        if not allowed_authority(request.headers.get('host',''),config.server.port,addresses):
            return JSONResponse({'detail':'invalid_host'},status_code=400)
        origin = request.headers.get('origin')
        if request.method in {'POST','PUT','DELETE','PATCH'}:
            if origin:
                parsed = urlparse(origin)
                if (parsed.scheme!='http' or not allowed_authority(parsed.netloc,config.server.port,addresses)
                        or parsed.netloc != request.headers.get('host') or parsed.path or parsed.query or parsed.fragment):
                    return JSONResponse({'detail':'invalid_origin'},status_code=403)
            elif request.headers.get('sec-fetch-site'):
                return JSONResponse({'detail':'origin_required'},status_code=403)
        public = request.url.path in {'/','/health','/ready','/v1/pairing/exchange'} or request.url.path.startswith('/assets/')
        if not public:
            try:
                request.state.identity = security.identity(request)
                if request.url.path.startswith('/v1/admin/'):
                    security.admin(request)
            except HTTPException as exc:
                return JSONResponse({'detail':exc.detail},status_code=exc.status_code,headers=exc.headers)
            except StorageUnavailable:
                return JSONResponse({'detail':'storage_unavailable'},status_code=503)
        response = await call_next(request)
        response.headers.update({'X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer','Cache-Control':'no-store',
            'Content-Security-Policy':"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' blob: data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"})
        return response

    web = Path(__file__).parent/'web'
    app.mount('/assets',StaticFiles(directory=web),name='assets')

    @app.get('/')
    def website():
        return FileResponse(web/'index.html',media_type='text/html')

    @app.get('/connection')
    def connection():
        return {'urls':connection_urls(),'port':config.server.port}

    @app.get('/connection/qr')
    def qr(address:str):
        if address not in connection_urls():
            raise HTTPException(422,'Choose an advertised local address')
        import qrcode
        data = BytesIO()
        qrcode.make(address).save(data,format='PNG')
        return Response(data.getvalue(),media_type='image/png')

    @app.post('/v1/admin/pairing')
    def pairing(request:Request):
        token = security.pairing()
        return {'token':token,'expires_in':120,'urls':[url+'#pair='+token for url in connection_urls()]}

    @app.post('/v1/pairing/exchange')
    def exchange(body:Exchange,request:Request):
        identifier,credential = security.exchange(body.token,request.client.host,body.name)
        response = JSONResponse({'client_id':identifier})
        response.set_cookie(COOKIE,credential,max_age=30*86400,httponly=True,samesite='strict',path='/')
        return response

    @app.get('/v1/admin/clients')
    def clients():
        return manager.repository.clients()

    @app.delete('/v1/admin/clients/{identifier}',status_code=204)
    def revoke(identifier:UUID):
        manager.repository.revoke_client(str(identifier))

    @app.get('/v1/admin/sessions')
    def sessions():
        return [manager.status(manager._hydrate(r)) for r in manager.repository.all()]

    @app.get('/health')
    def health():
        return {'status':'ok' if manager.storage_ok and manager.worker.is_alive() and not manager.worker_error and manager.model_ready else 'degraded',
                'demo':demo,'model':'demo' if demo else ('ready' if manager.model_ready else 'unavailable'),
                'worker':{'alive':manager.worker.is_alive(),'error':manager.worker_error},
                'storage':{'available':manager.storage_ok},
                'max_pages':config.pipeline.max_pages,'max_page_megabytes':config.server.max_page_megabytes,
                'max_input_megabytes':config.pipeline.max_input_megabytes}

    @app.get('/ready')
    def readiness():
        manager.available()
        return {'ready':True}

    @app.post('/preview')
    async def preview(request:Request):
        security.rate(('preview',request.state.identity),10)
        async with images.slot(preview=True):
            path,_,_ = await images.receive(request,config.paths.downloads)
            try:
                return Response(await images.preview(path),media_type='image/jpeg')
            finally:
                await asyncio.to_thread(path.unlink,missing_ok=True)

    @app.post('/v1/sessions',status_code=201)
    def create(body:CreateSession,request:Request):
        security.rate(('create',request.state.identity),10)
        return manager.status(manager.create(body.session_id,request.state.identity))

    @app.put('/v1/sessions/{identifier}/pages/{number}')
    async def upload(identifier:UUID,number:int,request:Request):
        if not 1 <= number <= config.pipeline.max_pages:
            raise HTTPException(422,'Page number outside supported range')
        job = await asyncio.to_thread(manager.get,identifier,request.state.identity)
        async with images.slot(), job.upload_lock:
            with manager.lease(job):
                path,count,sha = await images.receive(request,job.session.path/'incoming')
                published = None
                try:
                    job = await asyncio.to_thread(manager.get,identifier,request.state.identity)
                    existing = job.pages.get(number)
                    if existing:
                        if existing['sha256'] == sha:
                            return existing
                        raise HTTPException(409,'page_content_conflict')
                    if job.state != 'RECEIVING':
                        raise HTTPException(409,'session_already_submitted')
                    if sum(p['bytes'] for p in job.pages.values())+count > config.pipeline.max_input_megabytes*1024**2:
                        raise HTTPException(413,'session_input_limit')
                    info = await images.inspect(path)
                    extension = {'JPEG':'jpg','PNG':'png','HEIF':'heic','WEBP':'webp','TIFF':'tiff'}[info['format']]
                    name = f'page_{number:02d}.{extension}'
                    published = job.session.path/'incoming'/name
                    await asyncio.to_thread(path.replace,published)
                    page = dict(info,number=number,file=name,bytes=count,sha256=sha)
                    await asyncio.to_thread(manager.repository.add_page,job.session.id,page,config.pipeline.max_input_megabytes*1024**2)
                    published = None
                    return page
                except RepositoryConflict as exc:
                    raise HTTPException(409,str(exc)) from exc
                except RepositoryLimit as exc:
                    raise HTTPException(413,str(exc)) from exc
                except OSError as exc:
                    raise StorageUnavailable('Upload storage unavailable') from exc
                finally:
                    await asyncio.to_thread(path.unlink,missing_ok=True)
                    if published is not None:
                        try:
                            row = await asyncio.to_thread(manager.repository.get,job.session.id)
                            if not row or number not in row['pages']:
                                await asyncio.to_thread(published.unlink,missing_ok=True)
                        except StorageUnavailable:
                            # Leave an unacknowledged orphan for recovery; no metadata is invented.
                            pass

    @app.post('/v1/sessions/{identifier}/solve',status_code=202)
    async def solve(identifier:UUID,task:SubmitTask,request:Request):
        job = await asyncio.to_thread(manager.get,identifier,request.state.identity)
        async with job.upload_lock:
            await asyncio.to_thread(manager.submit,job,task)
        return await asyncio.to_thread(manager.status,job)

    @app.get('/v1/sessions/{identifier}/pages/{number}/preview')
    async def page_preview(identifier:UUID,number:int,request:Request):
        job=await asyncio.to_thread(manager.get,identifier,request.state.identity)
        if number not in job.pages:
            raise HTTPException(404,'Page not found')
        async with images.slot(preview=True):
            with manager.lease(job):
                data=await images.preview(job.session.path/'incoming'/job.pages[number]['file'])
                return Response(data,media_type='image/jpeg')

    @app.get('/v1/sessions/{identifier}')
    def status(identifier:UUID,request:Request):
        return manager.status(manager.get(identifier,request.state.identity))

    @app.post('/v1/sessions/{identifier}/render',status_code=202)
    def render(identifier:UUID,request:Request):
        manager.available()
        job = manager.get(identifier,request.state.identity)
        try:
            load_answer(job.session,job.verified_hash)
            manager.repository.retry_render(job.session.id)
        except RepositoryConflict as exc:
            raise HTTPException(409,str(exc)) from exc
        manager.wake.set()
        return manager.status(job)

    def completed(identifier,request):
        job = manager.get(identifier,request.state.identity)
        if job.state != 'COMPLETE':
            raise HTTPException(425,'Result is not ready')
        return job

    @app.get('/v1/sessions/{identifier}/result')
    def result(identifier:UUID,request:Request):
        job = completed(identifier,request)
        with manager.lease(job):
            return validate_outputs(job.session)

    @app.get('/v1/sessions/{identifier}/package')
    def package(identifier:UUID,request:Request):
        job = completed(identifier,request)
        return LeasedFileResponse(manager,job,job.session.path/'result.zip',media_type='application/zip',filename=f'vision-{identifier}.zip')

    @app.get('/v1/sessions/{identifier}/answer.txt')
    def text_answer(identifier:UUID,request:Request):
        job = manager.get(identifier,request.state.identity)
        if not manager.status(job)['answer_available']:
            raise HTTPException(425,'Answer is not ready')
        load_answer(job.session,job.verified_hash)
        return LeasedFileResponse(manager,job,job.session.path/'answer.txt',media_type='text/plain; charset=utf-8',filename=f'vision-{identifier}.txt')

    @app.get('/v1/sessions/{identifier}/cards/{index}')
    def card(identifier:UUID,index:int,request:Request,download:bool=False):
        job = completed(identifier,request)
        value = json.loads((job.session.path/'result.json').read_text(encoding='utf-8'))
        if not 1 <= index <= len(value['cards']):
            raise HTTPException(404,'Card not found')
        name = value['cards'][index-1]['file']
        return LeasedFileResponse(manager,job,job.session.path/'cards'/name,media_type='image/png',filename=name if download else None)

    @app.delete('/v1/sessions/{identifier}',status_code=204)
    def delete(identifier:UUID,request:Request):
        manager.delete(manager.get(identifier,request.state.identity))

    return app
