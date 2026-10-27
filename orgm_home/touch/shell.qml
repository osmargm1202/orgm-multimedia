// SPDX-License-Identifier: GPL-3.0-or-later
import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Wayland

Scope {
    id: root
    property bool opened: false
    property bool controlsOpened: false
    property bool controlsCollapsed: false
    property bool ready: false
    property string error: ""
    property real keyScale: 1
    property var panels: []
    property var capabilities: ({})
    property bool online: false
    property string activeName: "ORGM Home"
    property bool optionsOpened: false
    property bool appsOpened: false
    property var pairingRequests: []
    property bool pairingBusy: pairingDecision.running
    property bool powerOpened: false
    property var apps: []
    property var openedApps: []
    property string activeApp: "home"
    readonly property var openApps: apps.filter(app => app.id !== "home" && openedApps.includes(app.id))
    property string background: "costa"
    property int volume: 0
    property bool muted: false
    readonly property var backgrounds: [
        {id:"costa",name:"Costa nocturna",file:"home-night.webp"},
        {id:"bosque",name:"Bosque",file:"home-bosque.webp"},
        {id:"dunas",name:"Dunas",file:"home-dunas.webp"},
        {id:"orbita",name:"Órbita",file:"home-orbita.webp"},
        {id:"aurora",name:"Aurora",file:"home-aurora.webp"}
    ]
    readonly property string sourceOutput: Quickshell.env("ORGM_DISPLAY_SOURCE") || "eDP-1"
    readonly property string output: sourceOutput
    readonly property bool tabletMode: true

    function overlay(panel) { panel.WlrLayershell.layer = WlrLayer.Overlay; }
    function show() { powerOpened = false; appsOpened = false; opened = true; controlsOpened = true; hideControls.stop(); }
    function hide() { opened = false; for (var panel of panels) panel.reset(); send({action:"release"}); hideControls.restart(); }
    function toggle() { if (opened) hide(); else show(); }
    function collapseControls() { powerOpened = false; appsOpened = false; optionsOpened = false; hide(); controlsOpened = false; controlsCollapsed = true; hideControls.stop(); }
    function revealControls() { controlsCollapsed = false; controlsOpened = true; hideControls.restart(); }
    function retry() { if (!engine.running) { ready = false; error = ""; engine.running = true; } }
    function toggleApps() { var next=!appsOpened; powerOpened=false; optionsOpened=false; hide(); appsOpened=next; controlsOpened=true; if(next)hideControls.stop(); }
    function togglePower() { var next=!powerOpened; appsOpened=false; optionsOpened=false; hide(); powerOpened=next; controlsOpened=true; if(next)hideControls.stop(); }
    function closePower() { powerOpened=false; hideControls.restart(); }
    function selectApp(id) { if(control.running)return; appsOpened=false; act("switch-app",id); }
    function send(value) { if (engine.running) engine.write(JSON.stringify(value) + "\n"); }
    function act(action, argument) {
        if (control.running) return;
        if (action === "home") { appsOpened = false; powerOpened = false; }
        control.command = argument === undefined ? ["orgm-home-control", action] : ["orgm-home-control", action, argument];
        control.running = true;
        hideControls.restart();
    }
    function decidePairing(approve) {
        if(pairingDecision.running || !pairingRequests.length)return;
        pairingDecision.message=JSON.stringify({id:pairingRequests[0].id,approve:approve});
        pairingDecision.running=true;
    }
    Process {
        id:pairingStatus
        command:["orgm-home-control","pairing-pending"]
        stdout:SplitParser { onRead:data=>{try{var result=JSON.parse(data);var next=result.ok?result.data.requests:[];if(next.length && (!root.pairingRequests.length || root.pairingRequests[0].id!==next[0].id) && !pairingWake.running)pairingWake.running=true;root.pairingRequests=next;}catch(e){root.pairingRequests=[];}} }
        onExited:if(exitCode!==0)root.pairingRequests=[]
    }
    Timer { interval:20000;running:root.pairingRequests.length>0;onTriggered:pairingDim.running=true }
    Timer { interval:60000;running:root.pairingRequests.length>0;onTriggered:pairingSleep.running=true }
    Process { id:pairingDim;command:["orgm-home-control","pairing-dim"] }
    Process { id:pairingSleep;command:["orgm-home-control","pairing-sleep"] }
    Process { id:pairingWake;command:["orgm-home-control","pairing-wake"] }
    Process {
        id:pairingDecision
        property string message:""
        command:["orgm-home-control","pairing-decide"]
        stdinEnabled:true
        onStarted:{write(message+"\n");message="";}
        stdout:SplitParser { onRead:data=>{try{var result=JSON.parse(data);if(!result.ok)root.error=result.error;}catch(e){}} }
        onExited:if(!pairingStatus.running)pairingStatus.running=true
    }
    Timer { interval:1500;repeat:true;running:true;triggeredOnStart:true;onTriggered:if(!pairingStatus.running && !pairingDecision.running)pairingStatus.running=true }
    Timer { id: hideControls; interval: 8000; onTriggered: { if (!root.opened && !root.optionsOpened && !root.appsOpened && !root.powerOpened) root.controlsOpened = false; } }
    Process {
        id: engine
        command: [Quickshell.env("ORGM_OSK_ENGINE") || "orgm-osk-engine"]
        running: true
        stdinEnabled: true
        stdout: SplitParser {
            onRead: data => {
                try {
                    var message = JSON.parse(data);
                    if (message.event === "ready") { root.ready = true; root.error = ""; }
                    else if (message.event === "error") root.error = "Error de teclado: " + message.error;
                } catch(e) { root.error = "El teclado no respondió"; }
            }
        }
        onExited: { root.ready = false; root.error = "Teclado desconectado"; }
    }
    Process {
        id: control
        stdout: SplitParser { onRead: data => { try { var message=JSON.parse(data); if (!message.ok) root.error=message.error; else root.error=""; } catch(e) {} } }
    }
    Process {
        id: status
        command: ["orgm-home-control", "status"]
        stdout: SplitParser {
            onRead: data => {
                try {
                    var result=JSON.parse(data);
                    root.online=!!result.ok && !!result.data.session;
                    if (root.online) {
                        root.capabilities=result.data.capabilities || {};
                        root.activeName=result.data.title || "ORGM Home";
                        root.background=result.data.background || "costa";
                        root.volume=result.data.volume || 0;
                        root.muted=!!result.data.muted;
                        root.openedApps=result.data.open || [];
                        root.activeApp=result.data.app || "home";
                    }
                } catch(e) { root.online=false; }
            }
        }
    }
    Process {
        id: catalog
        command: ["orgm-home-control", "apps"]
        stdout: SplitParser { onRead: data => { try { var message=JSON.parse(data);if(message.ok)root.apps=message.data.apps || []; } catch(e) {} } }
    }
    Timer { interval: 1500; repeat: true; running: true; triggeredOnStart: true; onTriggered: { if (!status.running) status.running=true; if(!root.apps.length && !catalog.running)catalog.running=true; } }
    IpcHandler {
        target: "touch"
        function toggle(): void { root.toggle(); }
        function hide(): void { root.hide(); }
        function show(): void { root.show(); }
        function wifi(): void { root.powerOpened=false;root.appsOpened=false;root.optionsOpened=true;root.controlsOpened=true; }
        function apps(): void { root.toggleApps(); }
        function controls(): void { if (!root.controlsCollapsed) root.revealControls(); }
        function status(): string { return JSON.stringify({open:root.opened,ready:root.ready,online:root.online,error:root.error,output:root.sourceOutput,controls:root.controlsOpened,collapsed:root.controlsCollapsed,options:root.optionsOpened,apps:root.appsOpened,power:root.powerOpened,pairing:root.pairingRequests.length>0,panels:root.panels.map(p=>p.snapshot())}); }
    }
    Variants {
        model: Quickshell.screens.filter(s => s.name === root.sourceOutput)
        delegate: Scope {
            id: surface
            required property var modelData
            function reset() { board.reset(); }
            function buttonRect(button) { var pos=button.mapToItem(controls.contentItem,0,0);return {x:pos.x,y:pos.y+controls.margins.top,width:button.width,height:button.height}; }
            function snapshot() { return {screen:modelData.name,handle:{visible:handle.visible,x:12,y:12,width:handle.width,height:handle.height},controls:{x:(modelData.width-controlsBackground.width)/2,y:12,width:controlsBackground.width,height:controls.height,close:buttonRect(closePage),apps:buttonRect(switchApps),power:buttonRect(powerButton),hide:buttonRect(collapse)},pairing:{visible:pairingPicker.visible,x:(modelData.width-pairingView.width)/2,y:(modelData.height-pairingView.height)/2,buttons:pairingView.snapshot()},power:{visible:powerPicker.visible,x:(modelData.width-powerView.width)/2,y:100,buttons:powerView.snapshot()},switcher:{visible:appPicker.visible,x:(modelData.width-appView.width)/2,y:100,apps:appView.snapshot()},keyboard:{visible:keyboard.visible,x:(modelData.width-keyboardBackground.width)/2+10,y:modelData.height-keyboard.height+10,width:board.width,height:board.height},keys:board.snapshot()}; }
            Component.onCompleted: root.panels=[...root.panels,surface]
            Component.onDestruction: root.panels=root.panels.filter(p=>p!==surface)
            PanelWindow {
                id: handle
                screen: surface.modelData
                visible: !root.controlsOpened && !root.opened && !root.optionsOpened && !root.appsOpened && !root.powerOpened
                anchors { top:true; left:true }
                margins { top:12; left:12 }
                implicitWidth:52
                implicitHeight:44
                exclusionMode:ExclusionMode.Ignore
                focusable:false
                aboveWindows:true
                color:"transparent"
                Component.onCompleted:root.overlay(this)
                IconButton { anchors.fill:parent; icon:"show";label:"Mostrar controles";color:"#30161b27";onClicked:root.revealControls() }
            }
            PanelWindow {
                id: keyboard
                screen: surface.modelData
                visible: root.opened && !root.pairingRequests.length
                anchors { bottom:true; left:true; right:true }
                implicitHeight: Math.min(screen.height*0.48,330*root.keyScale)
                exclusionMode: ExclusionMode.Ignore
                focusable: false
                aboveWindows: true
                color: "transparent"
                Component.onCompleted: root.overlay(this)
                mask: Region { item: keyboardBackground }
                Rectangle {
                    id: keyboardBackground
                    anchors.horizontalCenter: parent.horizontalCenter
                    width: Math.min(parent.width-20,1120*root.keyScale)
                    height: parent.height
                    radius: 14
                    color: "#242d40"
                    Keyboard { id:board; anchors.fill:parent; anchors.margins:10; controller:root; allowShortcuts:false }
                }
            }
            PanelWindow {
                id: controls
                screen: surface.modelData
                visible: root.controlsOpened || root.opened || root.optionsOpened || root.appsOpened || root.powerOpened
                anchors { top:true; left:true; right:true }
                margins.top:12
                implicitHeight:80
                exclusionMode: ExclusionMode.Ignore
                focusable:false
                aboveWindows:true
                color:"transparent"
                Component.onCompleted:root.overlay(this)
                mask:Region { item:controlsBackground }
                Rectangle {
                    id:controlsBackground
                    anchors.horizontalCenter:parent.horizontalCenter
                    width:Math.min(parent.width-24,root.error?1000:680); height:parent.height; radius:16; color:"#f520293b"
                    Row {
                        x:12; anchors.verticalCenter:parent.verticalCenter; spacing:4
                        IconButton { icon:"home";label:"Inicio";available:root.online;onClicked:root.act("home") }
                        IconButton { id:switchApps;icon:"apps";label:"Cambiar de aplicación";available:root.online;onClicked:root.toggleApps() }
                        IconButton { icon:"back";label:"Atrás";available:root.online && !!root.capabilities.keys;onClicked:root.act("back") }
                        IconButton { id:closePage;icon:"close";label:"Cerrar página";available:root.online && !!root.capabilities.close;onClicked:root.act("close") }
                        Text { visible:!!root.error;width:Math.max(90,controlsBackground.width-681); anchors.verticalCenter:parent.verticalCenter; text:root.error; elide:Text.ElideRight; color:"#ffc0b6"; font.pixelSize:14 }
                        IconButton { icon:"volume-down";label:"Bajar volumen";available:root.online;onClicked:root.act("volume-down") }
                        IconButton { icon:root.muted?"mute":"volume";label:root.muted?"Activar audio":"Silenciar";available:root.online;onClicked:root.act("mute") }
                        Text { width:44; anchors.verticalCenter:parent.verticalCenter; text:root.volume+"%"; color:"#f2f5fc"; font.pixelSize:14; horizontalAlignment:Text.AlignHCenter }
                        IconButton { icon:"volume-up";label:"Subir volumen";available:root.online;onClicked:root.act("volume-up") }
                        IconButton { icon:"keyboard";label:"Teclado";onClicked:root.toggle() }
                        IconButton { id:powerButton;icon:"power";label:"Apagar o reiniciar";available:root.online;onClicked:root.togglePower() }
                        IconButton { id:collapse;icon:"hide";label:"Ocultar controles";onClicked:root.collapseControls() }
                    }
                }
            }
            PanelWindow {
                id:pairingPicker
                screen:surface.modelData
                visible:root.pairingRequests.length>0
                implicitWidth:Math.min(screen.width-32,560)
                implicitHeight:350
                exclusionMode:ExclusionMode.Ignore
                focusable:false
                aboveWindows:true
                color:"transparent"
                Component.onCompleted:root.overlay(this)
                PairingPanel { id:pairingView;anchors.fill:parent;controller:root }
            }
            PanelWindow {
                id:appPicker
                screen:surface.modelData
                visible:root.appsOpened && !root.pairingRequests.length
                anchors {top:true;left:true;right:true}
                margins.top:100
                implicitWidth:Math.min(screen.width-24,640)
                implicitHeight:Math.min(screen.height-126,420)
                exclusionMode:ExclusionMode.Ignore
                focusable:false
                aboveWindows:true
                color:"transparent"
                Component.onCompleted:root.overlay(this)
                mask:Region { item:appView }
                AppsPanel { id:appView;anchors.horizontalCenter:parent.horizontalCenter;width:Math.min(parent.width-24,640);height:parent.height;controller:root }
            }
            PanelWindow {
                id:powerPicker
                screen:surface.modelData
                visible:root.powerOpened && !root.pairingRequests.length
                anchors {top:true;left:true;right:true}
                margins.top:100
                implicitHeight:300
                exclusionMode:ExclusionMode.Ignore
                focusable:false
                aboveWindows:true
                color:"transparent"
                Component.onCompleted:root.overlay(this)
                mask:Region { item:powerView }
                PowerPanel { id:powerView;anchors.horizontalCenter:parent.horizontalCenter;width:Math.min(parent.width-24,440);height:parent.height;controller:root }
            }
            PanelWindow {
                screen:surface.modelData
                visible:root.optionsOpened && !root.pairingRequests.length
                anchors {top:true;right:true}
                margins {top:100;right:12}
                implicitWidth:Math.min(screen.width-24,640)
                implicitHeight:Math.min(screen.height-126,620)
                exclusionMode:ExclusionMode.Ignore
                WlrLayershell.keyboardFocus:WlrKeyboardFocus.Exclusive
                aboveWindows:true
                color:"transparent"
                Component.onCompleted:root.overlay(this)
                OptionsPanel { id:optionsView; anchors.fill:parent;controller:root }
            }
        }
    }
}
