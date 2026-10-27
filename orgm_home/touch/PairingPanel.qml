import QtQuick

Rectangle {
    id: menu
    required property var controller
    readonly property var request: controller.pairingRequests.length ? controller.pairingRequests[0] : ({})
    color: "#20293b"
    radius: 16
    Accessible.role: Accessible.Dialog
    Accessible.name: "Solicitud de vinculación"
    function snapshot() {
        var result={};
        for(var pair of [["reject",reject],["approve",approve]]) {
            var item=pair[1],pos=item.mapToItem(menu,0,0);
            result[pair[0]]={x:pos.x,y:pos.y,width:item.width,height:item.height};
        }
        return result;
    }
    Text { x:28;y:26;width:parent.width-56;text:"¿Autorizar este mando?";color:"#f2f5fc";font.pixelSize:26;font.bold:true }
    Text { x:28;y:82;width:parent.width-56;text:menu.request.name || "Dispositivo";color:"#f2f5fc";font.pixelSize:23;font.bold:true;elide:Text.ElideRight;textFormat:Text.PlainText }
    Text { x:28;y:120;width:parent.width-56;text:(menu.request.browser || "Navegador")+" pide permiso para controlar Jarq.";color:"#b5c2d9";font.pixelSize:18;wrapMode:Text.WordWrap;textFormat:Text.PlainText }
    Text { x:28;y:184;width:parent.width-56;text:"Acepta solo si reconoces la solicitud. Podrás revocar el acceso en Administración.";color:"#b5c2d9";font.pixelSize:17;wrapMode:Text.WordWrap }
    component Decision: Rectangle {
        required property string label
        required property bool approved
        height:58;radius:12
        opacity:menu.controller.pairingBusy ? 0.5 : 1
        color:hit.pressed?"#52617d":approved?"#b9c9ff":"#34415b"
        Accessible.role:Accessible.Button
        Accessible.name:label
        Accessible.onPressAction:menu.controller.decidePairing(approved)
        Text { anchors.centerIn:parent;text:parent.label;color:parent.approved?"#161b27":"#f2f5fc";font.pixelSize:18;font.bold:true }
        MouseArea { id:hit;anchors.fill:parent;enabled:!menu.controller.pairingBusy;onClicked:menu.controller.decidePairing(parent.approved) }
    }
    Row {
        x:28;y:264;width:parent.width-56;spacing:14
        Decision { id:reject;width:(parent.width-14)/2;label:"No, rechazar";approved:false }
        Decision { id:approve;width:(parent.width-14)/2;label:"Sí, autorizar";approved:true }
    }
}
