"""Real WayVNC/noVNC integration on the caller's private headless compositor."""
import asyncio
import contextlib
import json
import os
import io
from PIL import Image
from pathlib import Path
import socket
import uvicorn

from orgm_home.config import Settings
from orgm_home.web import create_app
import orgm_home.web as web_module


async def verify(p, page, root, tool, env, start, screen):
    novnc = next(Path(path)/'share/webapps/novnc' for path in
                 __import__('subprocess').check_output(['nix-store','-qR',str(root/'system')],text=True).splitlines()
                 if (Path(path)/'share/webapps/novnc/core/rfb.js').exists())
    endpoint=root/'live.sock'
    backend=start([tool('wayvnc'),'-C','/dev/null','--disable-input','--disable-resizing','--render-cursor','-f','20','-o','HEADLESS-1','-S',str(root/'live-control.sock'),'unix:'+str(endpoint)],'live')
    for _ in range(100):
        if endpoint.is_socket():break
        await asyncio.sleep(.05)
    assert endpoint.is_socket()
    listener=socket.socket();listener.bind(('127.0.0.1',0));listener.listen();listener.setblocking(False)
    base='http://127.0.0.1:'+str(listener.getsockname()[1])
    catalog=root/'live-catalog.json';catalog.write_text(json.dumps({'apps':[
        {'id':'home','type':'internal','name':'Home','workspace':'1'},
        {'id':'browser','type':'chrome','name':'Browser','workspace':'7','url':'about:blank'}]}))
    token=root/'live-token';token.write_text('isolated-test-token-not-a-real-room-token')
    class Agent:
        def __init__(self):self.calls=[];self.closed=False
        async def call(self,action,**data):
            self.calls.append(action)
            if action=='live-start':return {'viewer':'a'*32}
            if action=='live-close':self.closed=True;return {'closed':True}
            if action=='screen-prepare':return await screen.prepare()
            if action=='pointer':return await screen.click(data['frame'],data['x'],data['y'])
            if action=='status':return {'session':True,'app':'browser','open':['home','browser'],'volume':40,'muted':False,'capabilities':{'pointer':True},'previews':{}}
            return {}
    agent=Agent()
    previous_socket=web_module.LIVE_SOCKET;web_module.LIVE_SOCKET=str(endpoint)
    previous_client=os.environ.get('ORGM_VNC_CLIENT');os.environ['ORGM_VNC_CLIENT']=str(novnc)
    app=create_app(Settings(catalog,root/'unused-agent',token,(base,),require_access=False),agent)
    server=uvicorn.Server(uvicorn.Config(app,log_level='error',lifespan='off'))
    task=asyncio.create_task(server.serve(sockets=[listener]))
    viewer=None
    try:
        while not server.started:await asyncio.sleep(.05)
        await page.set_content('<style>body{background:#18202c}button{position:absolute;left:300px;top:200px;width:200px;height:100px;background:#00ff00}</style><button onclick="document.title=\'live-clicked\'">Target</button>')
        viewer=await p.chromium.launch(executable_path=tool('google-chrome-stable'),headless=True,args=['--no-sandbox','--disable-gpu'])
        phone=await viewer.new_page(viewport={'width':390,'height':844},has_touch=True)
        errors=[];phone.on('pageerror',lambda error:errors.append(str(error)))
        response=await phone.request.post(base+'/api/session',data={'token':token.read_text()},headers={'Origin':base})
        assert response.ok
        await phone.goto(base)
        await phone.locator('#open-screen').wait_for(state='visible')
        await phone.wait_for_function('() => !document.querySelector("#open-screen").disabled')
        await phone.locator('#open-screen').click()
        await phone.wait_for_function('() => document.querySelector("#screen-message").textContent.startsWith("En directo.")',timeout=15000)
        canvas=phone.locator('#screen-live-view canvas')
        before=await canvas.screenshot()
        await page.evaluate("document.body.style.background='#cc2200'")
        await asyncio.sleep(.4)
        after=await canvas.screenshot()
        assert before!=after, 'VNC framebuffer did not update'
        await canvas.scroll_into_view_if_needed()
        pixels=Image.open(io.BytesIO(await canvas.screenshot())).convert('RGB')
        points=[(x,y) for y in range(pixels.height) for x in range(pixels.width) if (lambda c:c[1]>180 and c[0]<80 and c[2]<80)(pixels.getpixel((x,y)))]
        assert points, 'Touch target missing from live framebuffer'
        box=await canvas.bounding_box()
        x=sum(point[0] for point in points)/len(points)/pixels.width
        y=sum(point[1] for point in points)/len(points)/pixels.height
        await phone.touchscreen.tap(box['x']+box['width']*x,box['y']+box['height']*y)
        await asyncio.sleep(.5)
        await page.wait_for_function('document.title==="live-clicked"',timeout=5000)
        await phone.screenshot(path=str(root/'live-phone.png'),full_page=True)
        await phone.locator('#screen-exit').click()
        for _ in range(100):
            if agent.closed:break
            await asyncio.sleep(.05)
        assert agent.closed and 'screen-capture' not in agent.calls
        assert not page.is_closed() and not errors, errors
        print(json.dumps({'live_vnc':'PASS','checks':['real framebuffer updates','actual phone click reaches private Chrome','no JPEG polling','stream released on exit','main application survives'],'evidence':str(root/'live-phone.png')}))
    finally:
        if viewer:await viewer.close()
        server.should_exit=True
        await task
        listener.close()
        web_module.LIVE_SOCKET=previous_socket
        if previous_client is None:os.environ.pop('ORGM_VNC_CLIENT',None)
        else:os.environ['ORGM_VNC_CLIENT']=previous_client
        backend.terminate()
        await asyncio.to_thread(backend.wait,5)
