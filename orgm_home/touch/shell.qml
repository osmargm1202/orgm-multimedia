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
    property string background: "costa"
    property int volume: 0
    property bool muted: false
    readonly property var backgrounds: [
        {id:"costa",name:"Costa nocturna",file:"home-night.png"},
        {id:"bosque",name:"Bosque",file:"home-bosque.png"},
        {id:"dunas",name:"Dunas",file:"home-dunas.png"},
        {id:"orbita",name:"Órbita",file:"home-orbita.png"},
        {id:"aurora",name:"Aurora",file:"home-aurora.png"}
    ]
    readonly property string sourceOutput: Quickshell.env("ORGM_DISPLAY_SOURCE") || "eDP-1"
    readonly property string output: sourceOutput
    readonly property bool tabletMode: true

    function overlay(panel) { panel.WlrLayershell.layer = WlrLayer.Overlay; }
    function show() { opened = true; controlsOpened = true; hideControls.stop(); }
    function hide() { opened = false; for (var panel of panels) panel.reset(); send({action:"release"}); hideControls.restart(); }
    function toggle() { if (opened) hide(); else show(); }
    function collapseControls() { optionsOpened = false; hide(); controlsOpened = false; controlsCollapsed = true; hideControls.stop(); }
    function revealControls() { controlsCollapsed = false; controlsOpened = true; hideControls.restart(); }
    function retry() { if (!engine.running) { ready = false; error = ""; engine.running = true; } }
    function send(value) { if (engine.running) engine.write(JSON.stringify(value) + "\n"); }
    function act(action, argument) {
        if (control.running) return;
        control.command = argument === undefined ? ["orgm-home-control", action] : ["orgm-home-control", action, argument];
        control.running = true;
        hideControls.restart();
    }
    Timer { id: hideControls; interval: 8000; onTriggered: { if (!root.opened && !root.optionsOpened) root.controlsOpened = false; } }
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
                    }
                } catch(e) { root.online=false; }
            }
        }
    }
    Timer { interval: 1500; repeat: true; running: true; triggeredOnStart: true; onTriggered: { if (!status.running) status.running=true; } }
    IpcHandler {
        target: "touch"
        function toggle(): void { root.toggle(); }
        function hide(): void { root.hide(); }
        function show(): void { root.show(); }
        function wifi(): void { root.optionsOpened=true;root.controlsOpened=true; }
        function controls(): void { if (!root.controlsCollapsed) root.revealControls(); }
        function status(): string { return JSON.stringify({open:root.opened,ready:root.ready,online:root.online,error:root.error,output:root.sourceOutput,controls:root.controlsOpened,collapsed:root.controlsCollapsed,options:root.optionsOpened,panels:root.panels.map(p=>p.snapshot())}); }
    }
    Variants {
        model: Quickshell.screens.filter(s => s.name === root.sourceOutput)
        delegate: Scope {
            id: surface
            required property var modelData
            function reset() { board.reset(); }
            function buttonRect(button) { var pos=button.mapToItem(controls.contentItem,0,0);return {x:pos.x,y:pos.y+controls.margins.top,width:button.width,height:button.height}; }
            function snapshot() { return {screen:modelData.name,handle:{visible:handle.visible,x:12,y:12,width:handle.width,height:handle.height},controls:{x:(modelData.width-controlsBackground.width)/2,y:12,width:controlsBackground.width,height:controls.height,close:buttonRect(closePage),hide:buttonRect(collapse)},keyboard:{visible:keyboard.visible,x:(modelData.width-keyboardBackground.width)/2+10,y:modelData.height-keyboard.height+10,width:board.width,height:board.height},keys:board.snapshot()}; }
            Component.onCompleted: root.panels=[...root.panels,surface]
            Component.onDestruction: root.panels=root.panels.filter(p=>p!==surface)
            PanelWindow {
                id: handle
                screen: surface.modelData
                visible: !root.controlsOpened && !root.opened && !root.optionsOpened
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
                visible: root.opened
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
                visible: root.controlsOpened || root.opened || root.optionsOpened
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
                    width:Math.min(parent.width-24,root.error?880:560); height:parent.height; radius:16; color:"#f520293b"
                    Row {
                        x:12; anchors.verticalCenter:parent.verticalCenter; spacing:4
                        IconButton { icon:"home";label:"Inicio";available:root.online;onClicked:root.act("home") }
                        IconButton { icon:"back";label:"Atrás";available:root.online && !!root.capabilities.keys;onClicked:root.act("back") }
                        IconButton { id:closePage;icon:"close";label:"Cerrar página";available:root.online && !!root.capabilities.close;onClicked:root.act("close") }
                        Text { visible:!!root.error;width:Math.max(90,controlsBackground.width-561); anchors.verticalCenter:parent.verticalCenter; text:root.error; elide:Text.ElideRight; color:"#ffc0b6"; font.pixelSize:14 }
                        IconButton { icon:"volume-down";label:"Bajar volumen";available:root.online;onClicked:root.act("volume-down") }
                        IconButton { icon:root.muted?"mute":"volume";label:root.muted?"Activar audio":"Silenciar";available:root.online;onClicked:root.act("mute") }
                        Text { width:44; anchors.verticalCenter:parent.verticalCenter; text:root.volume+"%"; color:"#f2f5fc"; font.pixelSize:14; horizontalAlignment:Text.AlignHCenter }
                        IconButton { icon:"volume-up";label:"Subir volumen";available:root.online;onClicked:root.act("volume-up") }
                        IconButton { icon:"keyboard";label:"Teclado";onClicked:root.toggle() }
                        IconButton { id:collapse;icon:"hide";label:"Ocultar controles";onClicked:root.collapseControls() }
                    }
                }
            }
            PanelWindow {
                screen:surface.modelData
                visible:root.optionsOpened
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
