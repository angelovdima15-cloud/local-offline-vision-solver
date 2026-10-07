import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "components"

ScrollView {
    contentWidth: availableWidth
    ColumnLayout {
        width: parent.width; spacing: 18
        Panel {
            Layout.fillWidth: true; implicitHeight: 170
            ColumnLayout {
                anchors.fill: parent; anchors.margins: 24
                Text { text: "Питание и закрытая крышка"; color: "#233b31"; font.pixelSize: 20; font.weight: Font.DemiBold }
                Switch { text: "Продолжать работу при подключённом питании"; checked: vision.powerEnabled; onClicked: vision.setPower(checked) }
                Text { text: "Экран может выключиться. Сон и гибернация останавливают вычисления. Настройки батареи не изменяются. Обеспечьте охлаждение ноутбука."; color: "#647261"; wrapMode: Text.Wrap; Layout.fillWidth: true; font.pixelSize: 13 }
                VisionButton { text: "Настройки питания Windows"; onClicked: vision.openPowerSettings() }
            }
        }
        Panel {
            Layout.fillWidth: true; implicitHeight: 244
            ColumnLayout {
                anchors.fill: parent; anchors.margins: 24; spacing: 12
                Text { text: "Данные и диагностика"; color: "#233b31"; font.pixelSize: 20; font.weight: Font.DemiBold }
                Text { text: vision.dataDirectory; color: "#647261"; Layout.fillWidth: true; elide: Text.ElideMiddle }
                Text { text: vision.diskSpace+" · завершённые задачи хранятся 24 часа"; color: "#647261" }
                RowLayout {
                    VisionButton { text: "Диагностика без фото"; onClicked: vision.exportDiagnostics() }
                    VisionButton { text: "Настройки сети"; onClicked: vision.openNetworkSettings() }
                    VisionButton { text: vision.ready ? "Остановить модель" : "Запустить модель"; enabled: !vision.busy; onClicked: vision.ready ? vision.stopModel() : vision.startBackend() }
                }
                VisionButton { text: "Разрешить локальную сеть · UAC"; onClicked: vision.allowFirewall() }
            }
        }
        Text { text: "Подключённые устройства"; color: "#233b31"; font.pixelSize: 20; font.weight: Font.DemiBold }
        Repeater {
            model: vision.clients
            delegate: RowLayout {
                required property var modelData
                Layout.fillWidth: true
                Text { text: modelData.name; color: "#202820"; Layout.fillWidth: true }
                VisionButton { text: "Отключить"; onClicked: vision.revokeClient(modelData.id) }
            }
        }
        Text { text: "Обновления приложения и модели выполняются только явно. Проверка ответа всегда включена."; color: "#647261"; wrapMode: Text.Wrap; Layout.fillWidth: true }
    }
}
