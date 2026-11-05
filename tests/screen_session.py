"""Private headless Sway + Chrome: capture and native click; no live session use.
Run: PYTHONPATH=. uv run --with playwright --with pillow python tests/screen_session.py SYSTEM
"""
import asyncio
import contextlib
import http.server
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
import time
from unittest.mock import patch
from playwright.async_api import async_playwright
from PIL import Image
from orgm_home.screen import ScreenControl
from helpers.wayland_pointer import Pointer
from orgm_home.agent import Controller
from orgm_home.browser_control import BrowserControl
from orgm_home.config import App
from orgm_home.native_text import encode_text
import orgm_home.agent as agent_module

async def main():
    root=Path(tempfile.mkdtemp(prefix='orgm-screen-native-'))
    system=Path(sys.argv[1]);binary=system/'sw/bin'
    (root/'system').symlink_to(system)
    requisites=subprocess.check_output(['nix-store','-qR',str(system)],text=True).splitlines()
    def tool(name):
        direct=binary/name
        if direct.exists():return str(direct)
        for path in requisites:
            candidate=Path(path)/'bin'/name
            if candidate.exists():return str(candidate)
        raise RuntimeError('Missing tool '+name)
    runtime=root/'runtime';runtime.mkdir(mode=0o700)
    home=root/'home';home.mkdir()
    config=root/'sway.conf';config.write_text('output * mode 1280x720\noutput * bg #18202c solid_color\ndefault_border none\nfocus_follows_mouse no\n')
    env={k:v for k,v in os.environ.items() if k not in {'SWAYSOCK','WAYLAND_DISPLAY','WAYLAND_SOCKET','DISPLAY','DBUS_SESSION_BUS_ADDRESS','HYPRLAND_INSTANCE_SIGNATURE','PYTHONPATH'}}
    env.update(HOME=str(home),XDG_RUNTIME_DIR=str(runtime),WLR_BACKENDS='headless',WLR_HEADLESS_OUTPUTS='1',WLR_RENDERER='pixman',WLR_LIBINPUT_NO_DEVICES='1',LIBGL_ALWAYS_SOFTWARE='1',XDG_SESSION_TYPE='wayland')
    os.environ['ORGM_PREVIEW_DIR']=str(root/'images')
    processes=[];logs=[];pointer=None;keyboard_process=None;seed_keyboard=None
    def start(args,label):
        log=(root/(label+'.log')).open('wb');logs.append(log)
        proc=subprocess.Popen(args,env=env,stdout=log,stderr=log,start_new_session=True);processes.append(proc);return proc
    async def wait(predicate):
        for _ in range(150):
            value=predicate()
            if value:return value
            await asyncio.sleep(.1)
        raise RuntimeError('Session timeout: '+str(root))
    async def run(*args,**kwargs):
        proc=await asyncio.create_subprocess_exec(tool(args[0]),*args[1:],env=env,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
        stdout,stderr=await asyncio.wait_for(proc.communicate(),kwargs.get('timeout',8))
        if proc.returncode:raise RuntimeError(stderr.decode()[:1000])
        return stdout.decode()
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            body=b'<title>Screen fixture</title><style>body{background:#18202c}button{position:absolute;left:300px;top:200px;width:200px;height:100px;background:#00ff00}</style><button onclick="document.title=\'native-clicked\'">Target</button>'
            self.send_response(200);self.send_header('Content-Type','text/html');self.end_headers();self.wfile.write(body)
        def log_message(self,*args):pass
    server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        start([tool('sway'),'--config',str(config)],'sway')
        sock=await wait(lambda:next(runtime.glob('sway-ipc.*.sock'),None))
        display=await wait(lambda:next((p for p in runtime.glob('wayland-*') if not p.name.endswith('.lock')),None))
        env.update(SWAYSOCK=str(sock),WAYLAND_DISPLAY=display.name)
        # Headless has no physical mouse; register its pointer capability only.
        pointer=Pointer(display)
        seed_keyboard=await asyncio.create_subprocess_exec(tool('orgm-osk-engine'),env=env,stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.DEVNULL)
        ready=json.loads(await asyncio.wait_for(seed_keyboard.stdout.readline(),5));assert ready['event']=='ready'
        profile=home/'chrome'
        start([tool('google-chrome-stable'),'--no-sandbox','--test-type','--disable-gpu','--disable-dev-shm-usage','--ozone-platform=wayland','--remote-debugging-port=0','--no-first-run','--user-data-dir='+str(profile),'--app=http://127.0.0.1:'+str(server.server_port)],'chrome')
        portfile=profile/'DevToolsActivePort';await wait(portfile.exists)
        async with async_playwright() as p:
            browser=await p.chromium.connect_over_cdp('http://127.0.0.1:'+portfile.read_text().splitlines()[0])
            page=browser.contexts[0].pages[0];await page.locator('button').wait_for()
            await run('swaymsg','-r','fullscreen enable')
            await asyncio.sleep(2)
            agent_module.command=run
            controller=Controller.__new__(Controller)
            async def tree():return json.loads(await run('swaymsg','-r','-t','get_tree'))
            controller.tree=tree
            async def sway(value):
                result=json.loads(await run('swaymsg','-r',value));assert all(row['success'] for row in result)
            screen=ScreenControl(run,sway,controller.screen_context)
            start_time=time.perf_counter();frame=await screen.capture();capture_ms=round((time.perf_counter()-start_time)*1000)
            assert screen.path.read_bytes().startswith(b'\xff\xd8');size=screen.path.stat().st_size
            # Use the captured image, exactly as the phone does. Browser CSS
            # coordinates exclude its server/client-side window decorations.
            image=Image.open(screen.path).convert('RGB')
            points=[(x,y) for y in range(image.height) for x in range(image.width) if (lambda c:c[1]>180 and c[0]<80 and c[2]<80)(image.getpixel((x,y)))]
            assert points, 'Fixture target absent from screenshot'
            x=sum(p[0] for p in points)/len(points)/image.width
            y=sum(p[1] for p in points)/len(points)/image.height
            start_time=time.perf_counter();await screen.click(frame['frame'],x,y)
            await page.wait_for_function('document.title==="native-clicked"')
            click_ms=round((time.perf_counter()-start_time)*1000)
            await page.evaluate("document.body.style.height='3000px'")
            await asyncio.sleep(.8)
            frame=await screen.capture()
            await screen.scroll(frame['frame'],.75,.75,0,3)
            await page.wait_for_function('scrollY>0')
            down=await page.evaluate('scrollY')
            await screen.scroll(frame['frame'],.75,.75,0,-3)
            await page.wait_for_function('(before)=>scrollY<before',arg=down)
            # A private native keyboard remains alive for the whole query.
            from live_fixture import verify
            await verify(p,page,root,tool,env,start,screen)
            await page.set_content('<input id=field autofocus><script>field.onkeydown=e=>{if(e.key==="Enter")document.body.dataset.sent=field.value}</script>')
            await page.locator('#field').focus()
            # Like the real QML bar, the seed keyboard already owns the fixed
            # layout. The agent creates a second identical persistent keyboard.
            keyboard_process=await asyncio.create_subprocess_exec(tool('orgm-osk-engine'),env=env,stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.DEVNULL)
            ready=json.loads(await asyncio.wait_for(keyboard_process.stdout.readline(),5));assert ready['event']=='ready'
            controller.keyboard=keyboard_process
            query='Música áéíóú ñÑ üÜ 123 "cine" @#%&/¿?'
            for code,modifiers in encode_text(query):await controller.native_key(code,modifiers)
            await controller.native_key(28)
            await page.wait_for_function('(text)=>document.body.dataset.sent===text',arg=query)
            assert await page.locator('#field').input_value()==query
            # Screenshot field detection and scoped typing use the real DOM/CDP.
            focused=next(w for w in agent_module.windows(await tree()) if w.get('focused'))
            await sway(f"[con_id={focused['id']}] mark --add orgm-home-browser")
            controller.apps={'browser':App('browser','chrome','Browser','7')}
            controller.remote_editor=None
            port=int(portfile.read_text().splitlines()[0])
            browser_control=BrowserControl('browser',port)
            with patch('orgm_home.agent.BrowserControl',lambda *_:browser_control):
                metadata=await controller.keyboard_context(include_fields=True)
                assert metadata['editor'] and metadata['fields']
                token=metadata['editor']['token']
                await controller.keyboard_text({'editor':token,'text':'Texto del teléfono áñ','submit':True})
                await page.wait_for_function('document.body.dataset.sent==="Texto del teléfono áñ"')
            screen.close(screen.frame);assert not screen.path.exists()
            print(json.dumps({'result':'PASS','capture_ms':capture_ms,'click_ms':click_ms,'jpeg_bytes':size,'native_typing':'PASS','field_detection_and_enter':'PASS','evidence':str(root)}))
            await browser.close()
    finally:
        if keyboard_process and keyboard_process.returncode is None:
            keyboard_process.terminate()
            await keyboard_process.wait()
        if seed_keyboard and seed_keyboard.returncode is None:
            seed_keyboard.terminate()
            await seed_keyboard.wait()
        server.shutdown();server.server_close()
        if pointer:pointer.close()
        for process in reversed(processes):
            with contextlib.suppress(ProcessLookupError):os.killpg(process.pid,signal.SIGTERM)
        for process in processes:
            with contextlib.suppress(subprocess.TimeoutExpired):process.wait(timeout=5)
        for log in logs:log.close()

asyncio.run(main())
