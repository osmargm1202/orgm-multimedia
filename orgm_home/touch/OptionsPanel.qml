import QtQuick
import Quickshell
Rectangle {
    id: menu
    required property var controller
    color: "#20293b"
    radius: 18
    Text { x:24;y:22;text:"Wi-Fi";font.pixelSize:24;font.bold:true;color:"#f2f5fc" }
    IconButton { anchors {right:parent.right;top:parent.top;margins:12} icon:"close";label:"Cerrar Wi-Fi";onClicked:{menu.controller.optionsOpened=false;menu.controller.hide();} }
    WifiPanel { anchors {left:parent.left;right:parent.right;top:parent.top;bottom:parent.bottom;leftMargin:20;rightMargin:20;topMargin:90;bottomMargin:20} controller:menu.controller }
}
