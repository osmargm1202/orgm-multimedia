"""Real isolated CDP typing, focus validation, Enter and password privacy.
Run: uv run --with playwright python tests/browser_keyboard.py
"""
import asyncio,json,tempfile
from pathlib import Path
from playwright.async_api import async_playwright
from orgm_home.browser_control import BrowserControl
from orgm_home.protocol import ControlError

async def main():
    with tempfile.TemporaryDirectory(prefix='orgm-keyboard-') as temp:
        async with async_playwright() as p:
            context=await p.chromium.launch_persistent_context(temp,executable_path='/run/current-system/sw/bin/chromium',headless=True,args=['--remote-debugging-port=0','--remote-debugging-address=127.0.0.1'])
            page=context.pages[0]
            await page.set_content('<input id=q type=search value="previous"><input id=other value="untouched"><input id=secret type=password value="private-value"><div id=rich contenteditable=true>old</div><script>q.onkeydown=e=>{if(e.key==="Enter")document.body.dataset.submitted=q.value}</script>')
            await page.bring_to_front();await page.locator('#q').focus()
            port=int((Path(temp)/'DevToolsActivePort').read_text().splitlines()[0])
            control=BrowserControl('browser',port)
            info=await control.keyboard()
            assert len(info['fields'])==4 and info['focused']['type']=='search'
            assert 'private-value' not in json.dumps(info) and 'previous' not in json.dumps(info)
            field=info['focused']['id'];query='Música áñ 漢字 -- $(sin-shell) "comillas"'
            await control.keyboard(field,query,submit=True)
            assert await page.locator('#q').input_value()==query
            assert await page.locator('body').get_attribute('data-submitted')==query
            await page.locator('#other').focus()
            try:
                await control.keyboard(field,'wrong',True)
                raise AssertionError('Stale field accepted')
            except ControlError:pass
            assert await page.locator('#other').input_value()=='untouched'
            await page.locator('#secret').focus()
            info=await control.keyboard();assert info['focused']['type']=='password'
            assert 'private-value' not in json.dumps(info)
            await page.locator('#rich').focus();info=await control.keyboard()
            await control.keyboard(info['focused']['id'],'contenido nuevo',False)
            assert await page.locator('#rich').inner_text()=='contenido nuevo'
            await control.keyboard(info['focused']['id'],'',False)
            assert (await page.locator('#rich').inner_text()).strip()==''
            await page.set_content('<input autofocus value="new document">');await page.locator('input').focus()
            try:
                await control.keyboard(field,'wrong',True)
                raise AssertionError('Detached field accepted')
            except ControlError:pass
            assert await page.locator('input').input_value()=='new document'
            html='''<button class=searchTab onclick="setTimeout(()=>{this.outerHTML='<input type=search data-uia=search-box-input>';},150)">Search</button><script>document.onkeydown=e=>{if(e.key==='Enter')document.body.dataset.query=document.activeElement.value}</script>'''
            await page.route('https://www.netflix.com/**',lambda route:route.fulfill(body=html))
            await page.goto('https://www.netflix.com/browse')
            search=BrowserControl('netflix',port)
            await search.search('Película de prueba áñ')
            assert await page.locator('input').input_value()=='Película de prueba áñ'
            assert await page.locator('body').get_attribute('data-query')=='Película de prueba áñ'
            await context.close()
    print(json.dumps({'result':'PASS','checks':['real CDP text and Enter','Unicode and literal text','stale and detached fields rejected','password values never returned','contenteditable and clearing']}))
asyncio.run(main())
