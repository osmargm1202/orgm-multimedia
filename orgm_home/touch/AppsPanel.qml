import QtQuick
import Quickshell

Rectangle {
    id: picker
    required property var controller
    color: "#20293b"
    radius: 16
    function snapshot() {
        var result=[];
        for(var i=0;i<cards.count;i++){
            var card=cards.itemAt(i),pos=card.mapToItem(picker,0,0);
            result.push({id:card.modelData.id,x:pos.x,y:pos.y,width:card.width,height:card.height});
        }
        return result;
    }
    Text { x:24;y:24;text:"Cambiar de aplicación";font.pixelSize:22;font.bold:true;color:"#f2f5fc" }
    IconButton { anchors {right:parent.right;top:parent.top;margins:12} icon:"close";label:"Cerrar selector";onClicked:{picker.controller.appsOpened=false;picker.controller.hide();} }
    Text { x:24;y:60;text:"Abiertas en tu sala";font.pixelSize:14;color:"#b5c2d9" }
    Text { visible:!picker.controller.openApps.length;anchors.centerIn:parent;text:"No hay aplicaciones abiertas. Usa Inicio para abrir una.";width:parent.width-48;wrapMode:Text.WordWrap;font.pixelSize:18;color:"#b5c2d9";horizontalAlignment:Text.AlignHCenter }
    Flickable {
        id:scroll
        anchors {left:parent.left;right:parent.right;top:parent.top;bottom:parent.bottom;leftMargin:20;rightMargin:20;topMargin:96;bottomMargin:20}
        contentWidth:width;contentHeight:grid.height;clip:true;boundsBehavior:Flickable.StopAtBounds
        Flow {
            id:grid
            width:scroll.width;spacing:12
            Repeater {
                id:cards
                model:picker.controller.openApps
                delegate:Rectangle {
                    id:card
                    required property var modelData
                    readonly property bool selected:picker.controller.activeApp===modelData.id
                    width:(grid.width-24)/3;height:144;radius:12
                    color:hit.pressed?"#456482":hit.containsMouse?"#34415b":"#17283d"
                    border.width:selected?2:1;border.color:selected?"#8ec9ff":"#40516a"
                    Accessible.role:Accessible.Button
                    Accessible.name:modelData.name+(selected?", en pantalla":"")
                    Accessible.onPressAction:picker.controller.selectApp(modelData.id)
                    Image { x:6;y:6;width:parent.width-12;height:86;source:"file://"+(Quickshell.env("ORGM_ASSET_DIR") || Quickshell.shellPath("../static"))+"/cards/"+card.modelData.id+".png";fillMode:Image.PreserveAspectCrop }
                    Text { x:10;y:100;width:parent.width-20;text:card.modelData.name;elide:Text.ElideRight;font.pixelSize:16;font.bold:true;color:"#f2f5fc" }
                    Text { x:10;y:122;width:parent.width-20;text:card.selected?"En pantalla":"Cambiar";font.pixelSize:12;color:"#b5c2d9" }
                    MouseArea { id:hit;anchors.fill:parent;hoverEnabled:true;onClicked:picker.controller.selectApp(card.modelData.id) }
                }
            }
        }
    }
}
