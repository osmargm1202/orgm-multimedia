import QtQuick

Rectangle {
    id: menu
    required property var controller
    property string pending: ""
    color: "#20293b"
    radius: 16
    onVisibleChanged: pending=""
    function snapshot() {
        var result={};
        for(var pair of [["poweroff",shutdown],["reboot",restart],["cancel",cancel],["confirm",confirm]]){
            var item=pair[1],pos=item.mapToItem(menu,0,0);
            result[pair[0]]={x:pos.x,y:pos.y,width:item.width,height:item.height,visible:item.visible};
        }
        return result;
    }
    component Action: Rectangle {
        required property string label
        property bool danger: false
        signal clicked()
        height:56;radius:12
        color:hit.pressed?"#52617d":danger?"#6b3338":"#34415b"
        Accessible.role:Accessible.Button
        Accessible.name:label
        Accessible.onPressAction:clicked()
        Text { anchors.centerIn:parent;text:parent.label;color:"#f2f5fc";font.pixelSize:17;font.bold:true }
        MouseArea { id:hit;anchors.fill:parent;enabled:menu.controller.online;onClicked:parent.clicked() }
    }
    Text { x:24;y:24;width:parent.width-96;text:!menu.pending?"Encendido":menu.pending==="poweroff"?"¿Apagar Jarq?":"¿Reiniciar Jarq?";color:"#f2f5fc";font.pixelSize:24;font.bold:true }
    IconButton { anchors {right:parent.right;top:parent.top;margins:12} icon:"close";label:"Cerrar encendido";onClicked:menu.controller.closePower() }
    Column {
        visible:!menu.pending
        x:24;y:96;width:parent.width-48;spacing:16
        Action { id:shutdown;width:parent.width;label:"Apagar el equipo";onClicked:menu.pending="poweroff" }
        Action { id:restart;width:parent.width;label:"Reiniciar";onClicked:menu.pending="reboot" }
    }
    Text { visible:!!menu.pending;x:24;y:92;width:parent.width-48;wrapMode:Text.WordWrap;text:menu.pending==="poweroff"?"Se cerrarán las aplicaciones y el equipo se apagará.":"Se cerrarán las aplicaciones y Jarq volverá al inicio.";color:"#b5c2d9";font.pixelSize:17 }
    Row {
        visible:!!menu.pending
        x:24;y:204;width:parent.width-48;spacing:12
        Action { id:cancel;width:(parent.width-12)/2;label:"Cancelar";onClicked:menu.controller.closePower() }
        Action { id:confirm;width:(parent.width-12)/2;label:menu.pending==="poweroff"?"Apagar":"Reiniciar";danger:true;onClicked:{var action=menu.pending;menu.controller.closePower();if(action==="poweroff" || action==="reboot")menu.controller.act(action);} }
    }
}
