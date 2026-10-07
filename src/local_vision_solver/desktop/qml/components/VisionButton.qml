import QtQuick
import QtQuick.Controls

Button {
    id: control
    property bool primary: false
    implicitHeight: 46
    implicitWidth: Math.max(130, contentItem.implicitWidth + 36)
    font.pixelSize: 15
    contentItem: Text {
        text: control.text
        font: control.font
        color: control.enabled ? (control.primary ? "#ffffff" : "#233b31") : "#8e978f"
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
    }
    background: Rectangle {
        radius: 12
        color: !control.enabled ? "#e5e9e1" : control.primary ? (control.down ? "#162d23" : "#233b31") : (control.hovered ? "#e3ef9d" : "#ffffff")
        border.color: control.primary ? "transparent" : "#dce1d5"
    }
}
