import QtQuick
import Quickshell.Io

Item {
    id: wifi
    required property var controller
    property var networks: []
    property string connection: ""
    property string selected: ""
    property bool secured: false
    property string message: ""
    property string request: ""
    property bool busy: worker.running
    function run(action) {
        if (busy) return;
        message="";
        request=action==="wifi-connect"?JSON.stringify({ssid:selected,password:password.text}):"";
        worker.command=["orgm-home-control",action];
        worker.running=true;
    }
    Component.onCompleted: run("wifi-status")
    Process {
        id: worker
        stdinEnabled:true
        onStarted: { if(wifi.request) {write(wifi.request+"\n");wifi.request="";password.text="";} }
        stdout:SplitParser { onRead:data=>{
            try {
                var result=JSON.parse(data);
                if(!result.ok) wifi.message=result.error;
                else {wifi.networks=result.data.networks || [];wifi.connection=result.data.connection || "";wifi.message=wifi.connection?"Conectado a "+wifi.connection:"Elige tu red Wi-Fi";}
            } catch(e) {wifi.message="No se pudo consultar el Wi-Fi";}
        } }
    }
    Column {
        width:parent.width;spacing:14
        Text { width:parent.width;text:wifi.busy?"Conectando o buscando redes…":wifi.message || "Wi-Fi";textFormat:Text.PlainText;wrapMode:Text.WordWrap;color:"#b5c2d9";font.pixelSize:16 }
        Row {
            visible:!wifi.controller.opened
            spacing:12
            Rectangle { width:180;height:48;radius:10;color:search.pressed?"#52617d":"#34415b";opacity:wifi.busy?.4:1
                Text { anchors.centerIn:parent;text:"Buscar redes";color:"#f2f5fc";font.pixelSize:15 }
                MouseArea { id:search;anchors.fill:parent;enabled:!wifi.busy;onClicked:wifi.run("wifi-scan") }
            }
            Rectangle { width:180;height:48;radius:10;color:reconnect.pressed?"#52617d":"#34415b";opacity:wifi.busy?.4:1
                Text { anchors.centerIn:parent;text:"Reconectar";color:"#f2f5fc";font.pixelSize:15 }
                MouseArea { id:reconnect;anchors.fill:parent;enabled:!wifi.busy;onClicked:wifi.run("wifi-reconnect") }
            }
        }
        ListView {
            visible:!wifi.controller.opened
            width:parent.width;height:190;clip:true;spacing:6;model:wifi.networks
            delegate:Rectangle {
                required property var modelData
                width:ListView.view.width;height:56;radius:10;color:wifi.selected===modelData.ssid?"#3b4b70":"#29354b"
                Text { x:16;anchors.verticalCenter:parent.verticalCenter;width:parent.width-100;text:modelData.ssid;textFormat:Text.PlainText;elide:Text.ElideRight;color:"#f2f5fc";font.pixelSize:16 }
                Text { anchors {right:parent.right;rightMargin:16;verticalCenter:parent.verticalCenter} text:modelData.connected?"Conectada":modelData.signal+"%";color:"#b5c2d9";font.pixelSize:13 }
                MouseArea { anchors.fill:parent;enabled:!wifi.busy;onClicked:{wifi.selected=modelData.ssid;wifi.secured=modelData.secured;password.text="";} }
            }
        }
        Rectangle {
            visible:!!wifi.selected && wifi.secured;width:parent.width;height:54;radius:10;color:"#161b27";border.width:password.activeFocus?2:1;border.color:password.activeFocus?"#b9c9ff":"#52617d"
            Text { anchors {left:parent.left;leftMargin:16;verticalCenter:parent.verticalCenter} visible:!password.text && !password.activeFocus;text:"Contraseña (vacía si ya está guardada)";color:"#b5c2d9";font.pixelSize:14 }
            TextInput { id:password;anchors {fill:parent;margins:14} echoMode:TextInput.Password;maximumLength:64;color:"#f2f5fc";font.pixelSize:18;clip:true;onActiveFocusChanged:if(activeFocus) wifi.controller.show() }
        }
        Rectangle { width:parent.width;height:50;radius:10;visible:!!wifi.selected && !wifi.controller.opened;color:"#b9c9ff";opacity:wifi.busy?.4:1
            Text { anchors.centerIn:parent; width:parent.width-32;text:"Conectar a "+wifi.selected;textFormat:Text.PlainText;elide:Text.ElideRight;horizontalAlignment:Text.AlignHCenter;color:"#161b27";font.pixelSize:16;font.bold:true }
            MouseArea { anchors.fill:parent;enabled:!wifi.busy;onClicked:{wifi.controller.hide();wifi.run("wifi-connect");} }
        }
    }
}
