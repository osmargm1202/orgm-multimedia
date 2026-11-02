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
            for service,profile in PROFILES.items():
                # Profile-specific selector fixture verifies the real selector strings.
                await page.set_content('<input type=search data-uia=search-box-input><button data-testid=play-pause-button data-uia=control-play-pause-play onclick="this.dataset.clicked=1">Play</button>')
                result=await page.evaluate('('+SCRIPT+')', {**profile,'hosts':None,'action':'search'})
                assert result['ok'],service
                assert await page.locator('input').evaluate('(e)=>e===document.activeElement'),service
                result=await page.evaluate('('+SCRIPT+')', {**profile,'hosts':None,'action':'play'})
                assert result['ok'],service
                assert await page.locator('button').get_attribute('data-clicked')=='1',service
            await page.set_content('<p>No player</p>')
            result=await page.evaluate('('+SCRIPT+')', {'action':'play'})
            assert not result['ok']
            await context.close()
    print(json.dumps({'result':'PASS','checks':['real CDP transport','spatial selection','activation','four service search/play profiles','missing player']}))

asyncio.run(main())
