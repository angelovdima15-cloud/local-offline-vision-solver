import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "components"

ScrollView {
    contentWidth: availableWidth
    ColumnLayout {
        width: parent.width; spacing: 18
        Panel {
            Layout.fillWidth: true; implicitHeight: 190
            ColumnLayout {
                anchors.fill: parent; anchors.margins: 24; spacing: 12
                Text { text: "01 / Проверка компьютера"; color: "#233b31"; font.pixelSize: 19; font.weight: Font.DemiBold }
                RowLayout {
                    Layout.fillWidth: true; spacing: 28
                    Repeater {
                        model: [{title:"Видеокарта",value:setup.report.gpu?.length ? setup.report.gpu[0].name : "Драйвер NVIDIA не найден",ok:setup.report.gpu_ok},
                            {title:"Оперативная память",value:(setup.report.ram_gib || "—")+" GiB · рекомендуется 32",ok:setup.report.ram_ok},
                            {title:"Свободное место",value:(setup.report.disk_gib || "—")+" GiB · нужно 20",ok:setup.report.disk_ok}]
                        delegate: ColumnLayout {
                            required property var modelData
                            Layout.fillWidth: true
                            Text { text: modelData.title; color: "#647261"; font.pixelSize: 13 }
                            Text { text: modelData.value; color: "#202820"; wrapMode: Text.Wrap; Layout.fillWidth: true; font.pixelSize: 14 }
                            Text { text: modelData.ok ? "Готово" : "Проверьте конфигурацию"; color: modelData.ok ? "#507d43" : "#986a33"; font.pixelSize: 12 }
                        }
                    }
                }
                Text { text: "Windows 11 x64 · RTX 4060 Laptop 8 GB · NVIDIA driver ≥ 551.61. Драйвер: "+(setup.report.driver_ok ? "готов" : "проверьте совместимость"); color: "#647261"; wrapMode: Text.Wrap; Layout.fillWidth: true; font.pixelSize: 12 }
            }
        }
        Panel {
            Layout.fillWidth: true; implicitHeight: 126
            ColumnLayout {
                anchors.fill: parent; anchors.margins: 24
                Text { text: "02 / Место для данных"; color: "#233b31"; font.pixelSize: 19; font.weight: Font.DemiBold }
                RowLayout {
                    Layout.fillWidth: true
                    Text { text: setup.dataDirectory; color: "#647261"; elide: Text.ElideMiddle; Layout.fillWidth: true }
                    VisionButton { text: "Выбрать папку"; enabled: !setup.busy; onClicked: vision.chooseDataDirectory() }
                }
            }
        }
        Panel {
            Layout.fillWidth: true; implicitHeight: 240
            ColumnLayout {
                anchors.fill: parent; anchors.margins: 24; spacing: 14
                Text { text: "03 / Подготовка локальной модели"; color: "#233b31"; font.pixelSize: 19; font.weight: Font.DemiBold }
                Text { text: "Qwen3-VL 8B · Q4_K_M · F16 projector\nИнтернет нужен для первоначальной загрузки. Файлы проверяются по SHA256."; color: "#647261"; wrapMode: Text.Wrap; Layout.fillWidth: true; lineHeight: 1.4 }
                ProgressBar { Layout.fillWidth: true; value: setup.progress }
                Text { text: setup.message; color: "#202820"; wrapMode: Text.Wrap; Layout.fillWidth: true; font.pixelSize: 13 }
                RowLayout {
                    VisionButton { text: setup.busy ? "Пауза" : "Продолжить настройку"; primary: true; onClicked: setup.busy ? setup.pause() : setup.install() }
                    VisionButton { text: "Скачать заново"; enabled: !setup.busy; onClicked: setup.restartDownloads() }
                    VisionButton { text: "Драйвер NVIDIA"; onClicked: vision.openDriverPage() }
                }
                VisionButton { text: "Установить скачанный драйвер · UAC"; visible: !setup.report.driver_ok; onClicked: vision.installDriver() }
            }
        }
    }
}
