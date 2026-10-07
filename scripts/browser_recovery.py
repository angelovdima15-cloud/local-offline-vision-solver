"""Focused fault scenarios added to the authenticated browser acceptance."""
import json
import re
from playwright.sync_api import expect


def run_recovery(page,context,service,images):
    page.on('dialog',lambda dialog:dialog.accept())
    answer=page.evaluate('async () => await api(`/v1/sessions/${state.id}/result`)')
    identifier=answer['session_id']
    result_path=f'**/v1/sessions/{identifier}/result'
    # A successful status response must not reset the result failure counter.
    calls=[]
    def broken_result(route):
        calls.append(1);route.fulfill(status=500,json={'detail':'injected result failure'})
    context.route(result_path,broken_result)
    page.evaluate('() => { state.phase="processing"; resume(); }')
    page.locator('#resume').wait_for(state='visible',timeout=15000)
    assert len(calls)==3
    page.wait_for_timeout(1700);assert len(calls)==3
    context.unroute(result_path,broken_result)
    page.locator('#resume').click();page.locator('#result').wait_for(state='visible')
    page.wait_for_function("() => !running && state.phase === 'complete'")

    # Hold completion persistence across New Task; old answer must stay hidden.
    context.route(result_path,lambda route:route.fulfill(json=answer))
    page.evaluate('''() => {
        window.__originalStorage=storage;
        storage=async (action,value) => {
            if(action==="put" && value?.phase==="complete") {
                window.__savingResult=true;
                await new Promise(resolve=>window.__releaseSave=resolve);
            }
            return window.__originalStorage(action,value);
        };
        state.phase="processing"; resume();
    }''')
    page.wait_for_function('() => window.__savingResult === true')
    page.locator('#new-task').click()
    page.evaluate('() => { window.__releaseSave(); storage=window.__originalStorage; }')
    expect(page.locator('#result')).to_be_hidden()
    expect(page.locator('#empty-state')).to_be_visible()
    context.unroute(result_path)

    # URL lifetimes for rejected previews and removed accepted pages.
    page.evaluate('''() => {
        window.__createdUrls=[];window.__releasedUrls=[];
        const create=URL.createObjectURL.bind(URL),revoke=URL.revokeObjectURL.bind(URL);
        URL.createObjectURL=blob=>{ const value=create(blob);window.__createdUrls.push(value);return value; };
        URL.revokeObjectURL=value=>{ window.__releasedUrls.push(value);revoke(value); };
    }''')
    page.locator('#files-input').set_input_files(images[1:])
    page.locator('#reject-photo').click()
    assert page.evaluate('window.__createdUrls.every(u=>window.__releasedUrls.includes(u))')
    page.locator('#files-input').set_input_files(images[1:]);page.locator('#accept-photo').click()
    page.get_by_role('button',name='Удалить страницу 1',exact=True).click()
    assert page.evaluate('window.__createdUrls.every(u=>window.__releasedUrls.includes(u))')

    # A partially uploaded photo set becomes a fresh server UUID after editing.
    page.locator('#files-input').set_input_files(images[1:]);page.locator('#accept-photo').click()
    old=page.evaluate('''async () => {
        await api('/v1/sessions',json({session_id:state.id}));state.created=true;
        await upload(1,state.pages[0].file,epoch,state.id);return state.id;
    }''')
    page.locator('#files-input').set_input_files(images[1:]);page.locator('#accept-photo').click()
    new=page.evaluate('state.id');assert old!=new
    assert page.evaluate('!state.created && state.pages.length===2')

    # 404 clears server state, retains photos and retries upload/solve.
    page.evaluate('() => { state.created=true;state.phase="processing";resume(); }')
    expect(page.locator('#retry')).to_have_text('Отправить заново',timeout=5000)
    assert page.evaluate('state.pages.length===2 && !state.created && state.phase==="draft"')
    page.locator('#retry').click();page.locator('#result').wait_for(state='visible',timeout=15000)

    # Verified TXT remains downloadable after render failure; ZIP stays hidden.
    active=page.evaluate('state.id')
    status_route=re.compile(re.escape(service.base)+r'/v1/sessions/'+active+r'$')
    def render_failed(route):
        route.fulfill(json={'session_id':active,'state':'ANSWER_READY','answer_available':True,
                            'result_available':False,'output_error':{'code':'render_failed','message':'injected'}})
    context.route(status_route,render_failed)
    page.evaluate('() => { state.phase="processing";resume(); }')
    page.locator('#render-retry').wait_for(state='visible')
    expect(page.locator('#zip-download')).to_be_hidden()
    with page.expect_download() as pending:page.locator('#text-download').click()
    assert pending.value.suggested_filename.endswith('.txt')
    context.unroute(status_route,render_failed)

    # Expired device credentials stop polling and request a new QR.
    context.clear_cookies()
    page.evaluate('() => { state.phase="processing";resume(); }')
    expect(page.locator('#error-message')).to_contain_text('Сопряжение истекло',timeout=5000)
    page.goto(service.base+'/#pair='+service.pairing())
    expect(page.locator('#connection-label')).to_contain_text('проверка доставки')
    expect(page).to_have_url(service.base+'/',timeout=5000)
    return {'new_task_during_result_persistence':True,'missing_session_resends_photos':True,
            'result_retry_is_bounded':True,'edited_partial_upload_gets_new_uuid':True,
            'preview_and_page_urls_released':True,'render_failure_txt_available':True,'expired_pairing_recovery':True}
