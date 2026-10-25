import QtQuick
Rectangle {
    id: button
    property string icon: "home"
    property string label: ""
    property bool available: true
    signal clicked()
    implicitWidth: 52
    implicitHeight: 52
    radius: 12
    color: hit.pressed ? "#52617d" : hit.containsMouse ? "#34415b" : "transparent"
    opacity: available ? 1 : 0.35
    Accessible.role: Accessible.Button
    Accessible.name: label
    Accessible.onPressAction: if (button.available) button.clicked()
    Image { anchors.centerIn: parent; width: 25; height: 25; source: "../static/icons/" + button.icon + ".svg"; sourceSize.width: 32; sourceSize.height: 32 }
    MouseArea { id: hit; anchors.fill: parent; enabled: button.available; hoverEnabled: true; onClicked: button.clicked() }
}
