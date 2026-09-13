import QtQuick
import QtQuick.Layouts
import org.kde.kirigami as Kirigami

// One metric row: label, filled bar, value.
ColumnLayout {
    id: bar

    property string label: ""
    property real value: 0          // 0..100
    property string text: ""
    property color accent: "#4c8dff"

    spacing: 2

    RowLayout {
        Layout.fillWidth: true
        spacing: Kirigami.Units.smallSpacing

        Text {
            text: bar.label
            color: Kirigami.Theme.textColor
            opacity: 0.7
            font: Kirigami.Theme.smallFont
            Layout.fillWidth: true
            elide: Text.ElideRight
        }
        Text {
            text: bar.text
            color: Kirigami.Theme.textColor
            font.family: "monospace"
            font.pointSize: Kirigami.Theme.smallFont.pointSize
        }
    }

    // Track and fill are siblings: otherwise the opacity of the track
    // multiplies that of the fill and the bar becomes invisible.
    Item {
        Layout.fillWidth: true
        implicitHeight: Math.round(Kirigami.Units.gridUnit * 0.42)

        Rectangle {
            id: track
            anchors.fill: parent
            radius: height / 2
            color: Kirigami.Theme.textColor
            opacity: 0.13
        }
        Rectangle {
            anchors.left: parent.left
            height: parent.height
            radius: track.radius
            width: parent.width * Math.max(0, Math.min(1, bar.value / 100))
            color: bar.accent
            Behavior on width { NumberAnimation { duration: 350; easing.type: Easing.OutCubic } }
        }
    }
}
