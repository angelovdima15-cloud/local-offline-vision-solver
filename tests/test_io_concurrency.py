import asyncio
import httpx
from api_support import create_app,SECRET
from test_api import config


def test_slow_upload_does_not_block_health_and_idle_timeout(config):
    config.server.upload_idle_timeout_seconds=.2
    app=create_app(config,demo=True)
    async def run():
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app,client=('127.0.0.1',1234)),base_url='http://127.0.0.1:8765',headers={'Authorization':'Bearer '+SECRET}) as client:
                identifier=(await client.post('/v1/sessions',json={})).json()['session_id']
                started=asyncio.Event()
                async def slow():
                    yield b'header';started.set();await asyncio.sleep(1);yield b'body'
                request=asyncio.create_task(client.put(f'/v1/sessions/{identifier}/pages/1',content=slow()))
                await started.wait()
                health=await asyncio.wait_for(client.get('/health'),.15)
                assert health.status_code==200
                assert (await request).status_code==408
                assert not list((config.pipeline.session_directory/identifier/'incoming').glob('*.part'))
    asyncio.run(run())
