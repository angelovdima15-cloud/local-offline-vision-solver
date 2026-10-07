import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "components"

ColumnLayout {
    RowLayout {
        Layout.fillWidth: true
        VisionButton { text: "Скачать TXT"; primary: true; onClicked: vision.download(vision.result.session_id,"txt") }
        VisionButton { text: "Скачать ZIP"; enabled: !!vision.result.cards?.length; onClicked: vision.download(vision.result.session_id,"zip") }
        VisionButton { text: "Все PNG"; enabled: !!vision.result.cards?.length; onClicked: vision.download(vision.result.session_id,"png") }
        Item { Layout.fillWidth: true }
        VisionButton { text: "Папка"; onClicked: vision.openFolder(vision.result.session_id) }
    }
    RowLayout {
        visible: !vision.result.cards?.length
        Text { text: "Проверенный текст сохранён. Карточки можно подготовить повторно."; color: "#647261"; Layout.fillWidth: true; wrapMode: Text.Wrap }
        VisionButton { text: "Повторить render"; onClicked: vision.retryRender(vision.result.session_id) }
    }
    TabBar { id: tabs; Layout.fillWidth: true; TabButton { text: "Полный текст" } TabButton { text: "Карточки" } }
    StackLayout {
        currentIndex: tabs.currentIndex; Layout.fillWidth: true; Layout.fillHeight: true
        ScrollView {
            contentWidth: availableWidth
            TextArea { text: vision.result.plain_text_answer || ""; readOnly: true; selectByMouse: true; wrapMode: TextEdit.Wrap; padding: 24; font.pixelSize: 17; color: "#202820"; background: Rectangle { color: "#ffffff"; radius: 18 } }
        }
        ListView {
            model: vision.result.cards || []; spacing: 18; clip: true
            delegate: Image {
                required property var modelData
                source: "image://vision/card/"+vision.result.session_id+"/"+modelData.index
                width: ListView.view.width; height: width * modelData.height/modelData.width; fillMode: Image.PreserveAspectFit; asynchronous: true
            }
        }
    }
}
