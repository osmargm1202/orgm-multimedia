"""Isolated Chromium checks; no accounts, no Jarq session.
Run: uv run --with playwright python tests/browser_navigation.py
"""
import asyncio
import json
import tempfile
from pathlib import Path
from unittest.mock import patch
from playwright.async_api import async_playwright
from orgm_home.browser_control import BrowserControl, PROFILES, SCRIPT

async def main():
    with tempfile.TemporaryDirectory(prefix='orgm-nav-') as temp:
        root=Path(temp)
        async with async_playwright() as p:
            context=await p.chromium.launch_persistent_context(str(root/'.local/share/orgm-home/chrome/browser'),executable_path='/run/current-system/sw/bin/chromium',headless=True,args=['--remote-debugging-port=0','--remote-debugging-address=127.0.0.1'])
            page=context.pages[0]
            await page.set_content('''<style>button{position:absolute;width:120px;height:80px}#a{left:20px;top:20px}#b{left:200px;top:20px}#c{left:20px;top:160px}</style><button id=a>A</button><button id=b onclick="this.textContent='opened'">B</button><button id=c>C</button>''')
            await page.bring_to_front()
            with patch.object(Path,'home',return_value=root):
                control=BrowserControl('browser')
                await control.act('right')
                assert await page.locator('#a').get_attribute('data-orgm-selected') is not None
                await control.act('right')
                assert await page.locator('#b').get_attribute('data-orgm-selected') is not None
                await control.act('ok')
                assert await page.locator('#b').inner_text()=='opened'
                await control.act('left');await control.act('down')
                assert await page.locator('#c').get_attribute('data-orgm-selected') is not None
            control=BrowserControl('browser',int((root/'.local/share/orgm-home/chrome/browser/DevToolsActivePort').read_text().splitlines()[0]))
            generic_url='https://redirectus.net/us/us.html?p=us&d=redirectus.net&id=1817&v=20260917a&ref=gostreameast.one,,'
            await page.route('https://redirectus.net/**',lambda route:route.fulfill(body='<button>Browser target</button>'))
            await control.navigate(generic_url)
            await page.wait_for_url(generic_url)
            assert len(context.pages)==1 and page.url==generic_url
            for service,profile in PROFILES.items():
                # Profile-specific selector fixture verifies the real selector strings.
                await page.set_content('<input type=search data-uia=search-box-input><button data-testid=play-pause-button data-uia=control-play-pause-play onclick="this.dataset.clicked=1">Play</button>')
                result=await page.evaluate('('+SCRIPT+')', {**profile,'hosts':None,'action':'search'})
                assert result['ok'],service
                assert await page.locator('input').evaluate('(e)=>e===document.activeElement'),service
                result=await page.evaluate('('+SCRIPT+')', {**profile,'hosts':None,'action':'play'})
                assert result['ok'],service
                assert await page.locator('button').get_attribute('data-clicked')=='1',service
            port=int((root/'.local/share/orgm-home/chrome/browser/DevToolsActivePort').read_text().splitlines()[0])
            await page.route('https://www.netflix.com/**',lambda route:route.fulfill(body='<button data-uia="play-button" onclick="this.dataset.started=1">Play</button>'))
            remote=BrowserControl('netflix',port)
            await remote.navigate('https://www.netflix.com/title/81234567')
            await page.wait_for_url('https://www.netflix.com/title/81234567')
            await page.locator('button').wait_for()
            result=await remote.act('start',expected_id='81234567')
            assert result['navigation']=='start'
            assert await page.locator('button').get_attribute('data-started')=='1'
            await page.locator('button').evaluate('(e)=>e.removeAttribute("data-started")')
            try:
                await remote.act('start',expected_id='89999999')
                raise AssertionError('Wrong content must not start')
            except Exception as error:
                from orgm_home.protocol import ControlError
                assert isinstance(error,ControlError)
            assert await page.locator('button').get_attribute('data-started') is None
            await page.set_content('<p>No player</p>')
            result=await page.evaluate('('+SCRIPT+')', {'action':'play'})
            assert not result['ok']
            await context.close()
    print(json.dumps({'result':'PASS','checks':['real CDP transport','spatial selection','activation','four service search/play profiles','missing player']}))

asyncio.run(main())
