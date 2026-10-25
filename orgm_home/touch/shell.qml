// SPDX-License-Identifier: GPL-3.0-or-later
import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Wayland

Scope {
    id: root
    property bool opened: false
    property bool controlsOpened: false
    property bool ready: false
    property string error: ""
    property real keyScale: 1
    property var panels: []
    property var capabilities: ({})
    property bool online: false
    property string activeName: "ORGM Home"
    property bool handleQuiet: false
    readonly property string sourceOutput: Quickshell.env("ORGM_DISPLAY_SOURCE") || "eDP-1"
    readonly property string output: sourceOutput
    readonly property bool tabletMode: true

    function overlay(panel) { panel.WlrLayershell.layer = WlrLayer.Overlay; }
    function show() { opened = true; controlsOpened = true; hideControls.stop(); }
    function wakeHandle() { handleQuiet=false; quietHandle.restart(); }
    function hide() { opened = false; for (var panel of panels) panel.reset(); send({action:"release"}); hideControls.restart(); wakeHandle(); }
    function toggle() { if (opened) hide(); else show(); }
    function retry() { if (!engine.running) { ready = false; error = ""; engine.running = true; } }
    function send(value) { if (engine.running) engine.write(JSON.stringify(value) + "\n"); }
    function act(action) {
        if (control.running) return;
        control.command = ["orgm-home-control", action];
        control.running = true;
        hideControls.restart();
    }
    Timer { id: hideControls; interval: 8000; onTriggered: { if (!root.opened) root.controlsOpened = false; } }
    Timer { id: quietHandle; interval: 6000; running:true; onTriggered:root.handleQuiet=true }
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
        function controls(): void { root.controlsOpened=true; hideControls.restart(); }
        function status(): string { return JSON.stringify({open:root.opened,ready:root.ready,online:root.online,error:root.error,output:root.sourceOutput,controls:root.controlsOpened,handleQuiet:root.handleQuiet,panels:root.panels.map(p=>p.snapshot())}); }
    }
    Variants {
        model: Quickshell.screens.filter(s => s.name === root.sourceOutput)
        delegate: Scope {
            id: surface
            required property var modelData
            function reset() { board.reset(); }
            function snapshot() { return {screen:modelData.name,keyboard:{visible:keyboard.visible,x:(modelData.width-keyboardBackground.width)/2+10,y:modelData.height-keyboard.height+10,width:board.width,height:board.height},keys:board.snapshot()}; }
            Component.onCompleted: root.panels=[...root.panels,surface]
            Component.onDestruction: root.panels=root.panels.filter(p=>p!==surface)
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
                id: handle
                screen: surface.modelData
                visible: !root.controlsOpened && !root.opened
                anchors { bottom:true; left:true }
                margins { left:12; bottom:8 }
                implicitWidth: 164
                implicitHeight: 52
                exclusionMode: ExclusionMode.Ignore
                focusable: false
                aboveWindows: true
                color: "transparent"
                Component.onCompleted: root.overlay(this)
                Rectangle { anchors.centerIn:parent; width:128; height:34; radius:12; color:root.handleQuiet?"transparent":"#242d40"
                    Behavior on color { ColorAnimation { duration:450 } }
                    Text { anchors.centerIn:parent; text:"Mando táctil"; font.pixelSize:14; color:root.handleQuiet?"#8b8d94":"#f2f5fc"; Behavior on color { ColorAnimation { duration:450 } } }
                }
                MouseArea { anchors.fill:parent; hoverEnabled:true; onEntered:root.wakeHandle(); onExited:quietHandle.restart(); onClicked: { root.wakeHandle(); root.controlsOpened=true; hideControls.restart(); } }
            }
            PanelWindow {
                id: controls
                screen: surface.modelData
                visible: root.controlsOpened || root.opened
                anchors { bottom:true; left:true; right:true }
                margins.bottom: root.opened ? keyboard.height+8 : 8
                implicitHeight: 102
                exclusionMode: ExclusionMode.Ignore
                focusable: false
                aboveWindows: true
                color: "transparent"
                Component.onCompleted: root.overlay(this)
                mask: Region { item: controlsBackground }
                Rectangle {
                    id: controlsBackground
                    width: Math.min(parent.width-24,1060)
                    height: parent.height
                    anchors.horizontalCenter: parent.horizontalCenter
                    radius: 16
                    color: "#242d40"
                    Text { x:16; y:8; width:parent.width-32; text:root.error || root.activeName; textFormat:Text.PlainText; elide:Text.ElideRight; font.pixelSize:12; color:root.error?"#ffc0b6":"#b5c2d9" }
                    Row {
                        anchors { left:parent.left; right:parent.right; bottom:parent.bottom; margins:8 }
                        spacing: 6
                        Repeater {
                            model: [
                                {label:"Inicio",action:"home",cap:""}, {label:"Atrás",action:"back",cap:"keys"},
                                {label:"Play / pausa",action:"play",cap:"play"}, {label:"Detener",action:"stop",cap:"stop"},
                                {label:"Anterior",action:"previous",cap:"next"}, {label:"Siguiente",action:"next",cap:"next"},
                                {label:"Vol −",action:"volume-down",cap:""}, {label:"Vol +",action:"volume-up",cap:""},
                                {label:"Teclado",action:"keyboard",cap:""}, {label:"Voltear",action:"rotate",cap:""}, {label:"Ocultar",action:"hide",cap:""}
                            ]
                            delegate: Rectangle {
                                required property var modelData
                                readonly property bool available: modelData.action==="keyboard" || modelData.action==="hide" || (root.online && (modelData.cap==="" || !!root.capabilities[modelData.cap]))
                                width:(controlsBackground.width-16-60)/11
                                height:62
                                radius:10
                                color:mouse.pressed?"#b9c9ff":"#34415b"
                                opacity:available?1:0.35
                                Text { anchors.centerIn:parent; width:parent.width-6; horizontalAlignment:Text.AlignHCenter; wrapMode:Text.WordWrap; text:modelData.label; font.pixelSize:13; color:mouse.pressed?"#161b27":"#f2f5fc" }
                                MouseArea {
                                    id:mouse
                                    anchors.fill:parent
                                    enabled:parent.available
                                    onClicked: {
                                        if (modelData.action==="keyboard") root.toggle();
                                        else if (modelData.action==="hide") { root.hide(); root.controlsOpened=false; }
                                        else root.act(modelData.action);
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}
