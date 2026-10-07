import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "components"

ApplicationWindow {
    id: root
    width: 1100; height: 760; minimumWidth: 900; minimumHeight: 640
    visible: true
    title: vision.isDemo ? "Vision · TRANSPORT DEMO" : "Vision"
    color: "#f5f6f2"
    font.family: "Segoe UI"; font.pixelSize: 15
    onClosing: close => { close.accepted = false; root.hide() }
    RowLayout {
        anchors.fill: parent; spacing: 0
        Rectangle {
            Layout.fillHeight: true; Layout.preferredWidth: 210; color: "#233b31"
            ColumnLayout {
                anchors.fill: parent; anchors.margins: 22; spacing: 12
                Text { text: "vision"; color: "#e3ef9d"; font.pixelSize: 38; font.weight: Font.DemiBold; Layout.topMargin: 14 }
                Text { text: "Сфотографируйте.\nРешите. Проверьте."; color: "#bdcbbf"; lineHeight: 1.3; font.pixelSize: 14; Layout.bottomMargin: 28 }
                Repeater {
                    model: [{page:"home",label:"Главная"},{page:"tasks",label:"Задачи"},{page:"settings",label:"Настройки"}]
                    delegate: Button {
                        required property var modelData
                        Layout.fillWidth: true; implicitHeight: 48
                        onClicked: vision.navigate(modelData.page)
                        contentItem: Text { text: modelData.label; color: vision.page === modelData.page ? "#233b31" : "#e9eee5"; font.pixelSize: 16; verticalAlignment: Text.AlignVCenter; leftPadding: 16 }
                        background: Rectangle { radius: 12; color: vision.page === modelData.page ? "#e3ef9d" : "transparent" }
                    }
                }
                Item { Layout.fillHeight: true }
                Rectangle { Layout.fillWidth: true; height: 1; color: "#496053" }
                Text { text: vision.isDemo ? "DEMO · без модели" : "Локально на ноутбуке"; color: "#e3ef9d"; font.pixelSize: 13; Layout.topMargin: 10 }
                Text { text: "После установки — офлайн"; color: "#bdcbbf"; font.pixelSize: 11 }
            }
        }
        ColumnLayout {
            Layout.fillWidth: true; Layout.fillHeight: true; Layout.margins: 30; spacing: 20
            RowLayout {
                Layout.fillWidth: true
                ColumnLayout {
                    Text { text: ({setup:"Добро пожаловать",home:"Всё готово к вашей задаче",tasks:"Ваши задачи",result:"Проверенный ответ",settings:"Настройки приложения"})[vision.page]; color: "#202820"; font.pixelSize: 26; font.weight: Font.DemiBold }
                    Text { text: vision.message; color: "#647261"; font.pixelSize: 13; Layout.maximumWidth: 580; wrapMode: Text.Wrap }
                }
                Item { Layout.fillWidth: true }
                Rectangle { width: 10; height: 10; radius: 5; color: vision.ready ? "#81a75c" : "#c9a158" }
                Text { text: vision.ready ? "Готово" : vision.busy ? "Запуск…" : "Настройка"; color: "#233b31" }
            }
            Loader {
                Layout.fillWidth: true; Layout.fillHeight: true
                source: ({setup:"SetupPage.qml",home:"HomePage.qml",tasks:"TasksPage.qml",result:"ResultPage.qml",settings:"SettingsPage.qml"})[vision.page]
            }
        }
    }
}
