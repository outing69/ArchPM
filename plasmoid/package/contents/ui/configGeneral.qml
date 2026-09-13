import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts
import org.kde.kirigami as Kirigami

// Settings page of the widget (right-click -> Configure). The property names
// map onto the entries in config/main.xml with the cfg_ prefix.
Kirigami.FormLayout {
    id: page

    property int cfg_panelMode: 0
    property alias cfg_showGame: showGame.checked

    QQC2.ButtonGroup { id: modeGroup }

    QQC2.RadioButton {
        Kirigami.FormData.label: "In the panel, show:"
        text: "Percentages   (CPU 12% · GPU 83% · RAM 51%)"
        QQC2.ButtonGroup.group: modeGroup
        checked: page.cfg_panelMode === 0
        onToggled: if (checked) page.cfg_panelMode = 0
    }
    QQC2.RadioButton {
        text: "Temperatures   (CPU 56° · GPU 67°)"
        QQC2.ButtonGroup.group: modeGroup
        checked: page.cfg_panelMode === 1
        onToggled: if (checked) page.cfg_panelMode = 1
    }
    QQC2.RadioButton {
        text: "Both   (CPU 12% 56° · GPU 83% 67°)"
        QQC2.ButtonGroup.group: modeGroup
        checked: page.cfg_panelMode === 2
        onToggled: if (checked) page.cfg_panelMode = 2
    }

    Item { Kirigami.FormData.isSection: true }

    QQC2.CheckBox {
        id: showGame
        Kirigami.FormData.label: "Game:"
        text: "Show the running game's name in the panel"
    }

    QQC2.Label {
        Layout.fillWidth: true
        wrapMode: Text.WordWrap
        opacity: 0.7
        text: "Values turn red above 85 °C. These settings only affect the widget when it sits in a panel; on the desktop it always shows the full view."
    }
}
