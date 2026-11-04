import QtQuick
import Quickshell
Rectangle {
    id: button
    property string icon: "home"
    property string label: ""
    property bool available: true
    property bool checkable: false
    property bool checked: false
    signal clicked()
    implicitWidth: 56
    implicitHeight: 56
    radius: 12
    color: hit.pressed ? "#52617d" : hit.containsMouse ? "#34415b" : checked ? "#234d66" : "transparent"
    border.width: checked ? 1 : 0
    border.color: "#8ec9ff"
    opacity: available ? 1 : 0.35
    Accessible.role: Accessible.Button
    Accessible.name: label
    Accessible.checkable: checkable
    Accessible.checked: checked
    Accessible.onPressAction: if (button.available) button.clicked()
    Image { anchors.centerIn: parent; width: 28; height: 28; source: "file://" + (Quickshell.env("ORGM_ASSET_DIR") || Quickshell.shellPath("../static")) + "/icons/" + button.icon + ".svg"; sourceSize.width: 36; sourceSize.height: 36 }
    MouseArea { id: hit; anchors.fill: parent; enabled: button.available; hoverEnabled: true; onClicked: button.clicked() }
}
