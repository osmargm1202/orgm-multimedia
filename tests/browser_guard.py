"""Real isolated Chrome popup/tab guard; no live room or external sites."""
import asyncio
import json
import tempfile
from pathlib import Path

from playwright.async_api import async_playwright
from orgm_home.browser_guard import BrowserGuard


async def main():
    with tempfile.TemporaryDirectory(prefix='orgm-browser-guard-') as temp:
        root = Path(temp)
        async with async_playwright() as p:
            context = await p.chromium.launch_persistent_context(
                str(root / 'chrome'), executable_path='/run/current-system/sw/bin/chromium',
                headless=True, args=['--remote-debugging-port=0', '--remote-debugging-address=127.0.0.1'])
            page = context.pages[0]
            await page.goto('data:text/html,<h1>Main movie</h1>')
            port = int((root / 'chrome/DevToolsActivePort').read_text().splitlines()[0])
            guard = BrowserGuard(root)
            await guard.reconcile('browser', port)
            primary = guard.primary['browser']
            async with page.expect_popup() as event:
                await page.evaluate("window.open('about:blank','ad','width=500,height=400')")
            popup = await event.value
            async with popup.expect_event('close'):
                await guard.reconcile('browser', port)
            assert popup.is_closed() and not page.is_closed()
            tab = await context.new_page()
            await tab.goto('data:text/html,<h1>Extra tab</h1>')
            # An agent restart must not adopt the focused new tab as primary.
            restarted = BrowserGuard(root)
            async with tab.expect_event('close'):
                await restarted.reconcile('browser', port)
            assert tab.is_closed() and not page.is_closed()
            await page.goto('data:text/html,<h1>Next episode</h1>')
            await restarted.reconcile('browser', port)
            assert restarted.primary['browser'] == primary and not page.is_closed()
            # Ambiguous pre-existing independent tabs are left intact.
            ambiguous = await context.new_page()
            clean = root / 'new-state'; clean.mkdir()
            await BrowserGuard(clean).reconcile('browser', port)
            assert not ambiguous.is_closed() and not page.is_closed()
            await ambiguous.close()
            assert (root / 'browser-primary.json').stat().st_mode & 0o777 == 0o600
            await context.close()
    print(json.dumps({'result': 'PASS', 'checks': ['popup closed', 'independent tab closed', 'primary preserved across restart', 'same-page navigation preserved', 'ambiguous old session preserved', 'private state permissions']}))

asyncio.run(main())
