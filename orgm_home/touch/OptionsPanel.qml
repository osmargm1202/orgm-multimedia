import QtQuick
import Quickshell
Rectangle {
    id: menu
    required property var controller
    property string tab: "backgrounds"
    property string confirmation: ""
    color: "#20293b"
    radius: 18
    Text { x:24; y:22; text:"Opciones"; font.pixelSize:24; font.bold:true; color:"#f2f5fc" }
    IconButton { anchors { right:parent.right; top:parent.top; margins:12 } icon:"close"; label:"Cerrar opciones"; onClicked:{menu.confirmation="";menu.controller.optionsOpened=false;menu.controller.hide();} }
    Row {
        x:20; y:76; spacing:10
        Repeater {
            model:[{id:"wifi",label:"Wi-Fi"},{id:"backgrounds",label:"Fondos"},{id:"admin",label:"Administración"}]
            delegate: Rectangle {
                required property var modelData
                width: modelData.id==="admin"?180:116; height:48; radius:12
                color:menu.tab===modelData.id?"#3b4b70":"#29354b"
                Text { anchors.centerIn:parent; text:modelData.label; color:"#f2f5fc"; font.pixelSize:15 }
                MouseArea { anchors.fill:parent; onClicked:{menu.controller.optionsTab=modelData.id;menu.confirmation="";} }
            }
        }
    }
    Loader { anchors {left:parent.left;right:parent.right;top:parent.top;bottom:parent.bottom;leftMargin:20;rightMargin:20;topMargin:146;bottomMargin:20} active:menu.tab==="wifi";sourceComponent:WifiPanel {controller:menu.controller} }
    Column {
        x:20; y:146; width:parent.width-40; spacing:12; visible:menu.tab==="backgrounds"
        Text { text:"Elige el ambiente de tu sala."; color:"#b5c2d9"; font.pixelSize:15 }
        Grid {
            columns:2; spacing:12; width:parent.width
            Repeater {
                model:menu.controller.backgrounds
                delegate: Rectangle {
                    required property var modelData
                    width:(menu.width-52)/2; height:120; radius:12
                    color:menu.controller.background===modelData.id?"#b9c9ff":"#34415b"
                    Image { anchors {fill:parent;margins:3} source:"file://"+(Quickshell.env("ORGM_ASSET_DIR") || Quickshell.shellPath("../static"))+"/"+modelData.file; fillMode:Image.PreserveAspectCrop; asynchronous:true }
                    Rectangle { anchors {left:parent.left;right:parent.right;bottom:parent.bottom;margins:3} height:32; color:"#df161b27" }
                    Text { x:12; anchors.bottom:parent.bottom; anchors.bottomMargin:11; text:modelData.name; color:"#f2f5fc"; font.pixelSize:14 }
                    MouseArea { anchors.fill:parent; onClicked:menu.controller.act("background",modelData.id) }
                }
            }
        }
    }
    Column {
        x:20; y:146; width:parent.width-40; spacing:12; visible:menu.tab==="admin"
        Text { text:"Pantalla y equipo"; color:"#b5c2d9"; font.pixelSize:15 }
        Repeater {
            model:[
                {action:"rotate",label:"Voltear la pantalla",detail:"Alternar 0° / 180° en la laptop"},
                {action:"restart-launcher",label:"Reiniciar el launcher",detail:"Recuperar inicio, controles y espejo"},
                {action:"reboot",label:"Reiniciar el equipo",detail:"Cerrar la sesión y volver a iniciar Jarq"}
            ]
            delegate: Rectangle {
                required property var modelData
                width:menu.width-40; height:82; radius:12; color:hit.pressed?"#3b4b70":"#29354b"
                Image { x:18; anchors.verticalCenter:parent.verticalCenter; width:26; height:26; source:"file://" + (Quickshell.env("ORGM_ASSET_DIR") || Quickshell.shellPath("../static")) + "/icons/"+modelData.action+".svg" }
                Column { x:62; anchors.verticalCenter:parent.verticalCenter; spacing:7
                    Text { text:menu.confirmation===modelData.action?"Toca de nuevo para reiniciar":modelData.label; color:menu.confirmation===modelData.action?"#ffc0b6":"#f2f5fc"; font.pixelSize:16 }
                    Text { text:modelData.detail; color:"#b5c2d9"; font.pixelSize:13 }
                }
                MouseArea { id:hit; anchors.fill:parent; onClicked:{
                    if(modelData.action==="reboot" && menu.confirmation!=="reboot") menu.confirmation="reboot";
                    else {menu.confirmation="";menu.controller.act(modelData.action);}
                } }
            }
        }
        Text { width:parent.width; text:"El brillo baja al 20% a los 20 segundos y al 0% al minuto. Toca la pantalla para volver al 100%."; wrapMode:Text.WordWrap; color:"#b5c2d9"; font.pixelSize:14; lineHeight:1.4 }
    }
}
