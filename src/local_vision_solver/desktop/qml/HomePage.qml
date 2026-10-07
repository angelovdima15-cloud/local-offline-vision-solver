import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "components"

ScrollView {
    contentWidth: availableWidth
    ColumnLayout {
        width: parent.width; spacing: 20
        Panel {
            Layout.fillWidth: true; implicitHeight: 182; color: "#e3ef9d"; border.color: "#d8e48e"
            ColumnLayout {
                anchors.fill: parent; anchors.margins: 26; spacing: 10
                Text { text: "Все страницы. Полный ответ.\nНезависимая проверка."; font.pixelSize: 24; font.weight: Font.DemiBold; color: "#233b31"; lineHeight: 1.1 }
                RowLayout {
                    Text { text: "Добавьте фото с телефона или ноутбука"; color: "#536146"; Layout.fillWidth: true }
                    VisionButton { text: "Добавить фото"; primary: true; enabled: vision.ready; onClicked: vision.addPhotos() }
                }
            }
        }
        RowLayout {
            Layout.fillWidth: true; spacing: 18
            Panel {
                Layout.fillWidth: true; Layout.preferredWidth: 420; implicitHeight: 332
                ColumnLayout {
                    anchors.fill: parent; anchors.margins: 22; spacing: 12
                    Text { text: "Подключите iPhone"; color: "#233b31"; font.pixelSize: 20; font.weight: Font.DemiBold }
                    RowLayout {
                        Layout.fillWidth: true; spacing: 15
                        Image { source: "image://vision/qr?"+vision.qrRevision; sourceSize.width: 180; sourceSize.height: 180; Layout.preferredWidth: 180; Layout.preferredHeight: 180; cache: false }
                        Text { text: "Одна Wi-Fi сеть\n\nОткройте QR камерой. Код действует 120 секунд.\n\nСопряжение защищает доступ. HTTP не шифрует LAN-трафик."; Layout.fillWidth: true; wrapMode: Text.Wrap; color: "#647261"; font.pixelSize: 13 }
                    }
                    VisionButton { text: "Обновить QR"; enabled: vision.ready; onClicked: vision.pair() }
                    Text { text: vision.pairingUrls.length ? vision.pairingUrls[0].split("#")[0] : "Адрес сети появится после запуска"; color: "#647261"; font.pixelSize: 12; Layout.fillWidth: true; elide: Text.ElideMiddle }
                }
            }
            Panel {
                Layout.fillWidth: true; Layout.preferredWidth: 230; implicitHeight: 332
                ColumnLayout {
                    anchors.fill: parent; anchors.margins: 22; spacing: 14
                    Text { text: "На ноутбуке"; color: "#233b31"; font.pixelSize: 20; font.weight: Font.DemiBold }
                    Text { text: vision.clients.length+" подключённых устройств"; color: "#647261"; wrapMode: Text.Wrap; Layout.fillWidth: true }
                    Text { text: vision.tasks.filter(t=>["QUEUED","RUNNING","RENDERING","PACKAGING"].includes(t.state)).length+" задач в работе"; color: "#202820" }
                    Rectangle { Layout.fillWidth: true; height: 1; color: "#e1e5dc" }
                    Text { text: "Работать с закрытой крышкой\nПри подключённом питании"; color: "#202820"; wrapMode: Text.Wrap; Layout.fillWidth: true }
                    Switch { checked: vision.powerEnabled; onClicked: vision.setPower(checked) }
                    Item { Layout.fillHeight: true }
                    Text { text: vision.diskSpace; color: "#647261"; font.pixelSize: 12 }
                }
            }
        }
    }
}
