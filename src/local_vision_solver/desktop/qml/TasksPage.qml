import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "components"

ColumnLayout {
    RowLayout {
        Layout.fillWidth: true
        Text { text: vision.tasks.length+" задач · фотографии хранятся на этом ноутбуке"; color: "#647261"; Layout.fillWidth: true }
        VisionButton { text: "Добавить фото"; primary: true; enabled: vision.ready; onClicked: vision.addPhotos() }
    }
    ListView {
        Layout.fillWidth: true; Layout.fillHeight: true; clip: true; spacing: 12
        model: vision.tasks
        delegate: Panel {
            required property var modelData
            width: ListView.view.width; height: 112
            RowLayout {
                anchors.fill: parent; anchors.margins: 18; spacing: 16
                Image { source: modelData.page_count ? "image://vision/page/"+modelData.session_id+"/1" : ""; sourceSize.width: 70; sourceSize.height: 76; Layout.preferredWidth: 70; Layout.preferredHeight: 76; fillMode: Image.PreserveAspectCrop; asynchronous: true }
                ColumnLayout {
                    Layout.fillWidth: true
                    Text { text: new Date(modelData.created_at*1000).toLocaleString(Qt.locale("ru_RU"),"dd MMM · hh:mm"); color: "#202820"; font.pixelSize: 16; font.weight: Font.DemiBold }
                    Text { text: ({RECEIVING:"Принимаем фото",QUEUED:"В очереди",RUNNING:"Решаем и проверяем",ANSWER_READY:"Текст готов",RENDERING:"Готовим карточки",PACKAGING:"Готовим ZIP",COMPLETE:"Готово",ERROR:"Ошибка"})[modelData.state]+" · "+modelData.page_count+" стр."; color: modelData.state==="ERROR" ? "#a55540" : "#647261" }
                    Text { text: modelData.error?.message || modelData.output_error?.message || modelData.stage || ""; color: "#647261"; Layout.fillWidth: true; elide: Text.ElideRight; font.pixelSize: 12 }
                }
                VisionButton { text: "Открыть"; enabled: modelData.answer_available; onClicked: vision.openResult(modelData.session_id) }
                Button { text: "×"; implicitWidth: 42; implicitHeight: 44; enabled: !["QUEUED","RUNNING","RENDERING","PACKAGING"].includes(modelData.state); onClicked: vision.deleteTask(modelData.session_id) }
            }
        }
        Text { anchors.centerIn: parent; visible: !vision.tasks.length; text: "Здесь появятся ваши задания"; color: "#647261" }
    }
}
