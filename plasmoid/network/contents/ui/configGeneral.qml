import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts
import org.kde.kirigami as Kirigami

// Settings page of the widget (right-click -> Configure). The property names
// map onto the entries in config/main.xml with the cfg_ prefix.
Kirigami.FormLayout {
    id: page

    property alias cfg_showVpn: showVpn.checked
    property alias cfg_showTop: showTop.checked

    QQC2.CheckBox {
        id: showVpn
        Kirigami.FormData.label: "In the panel:"
        text: "Show \"VPN\" while a VPN tunnel is up"
    }
    QQC2.CheckBox {
        id: showTop
        text: "Show the name of the program using the most bandwidth"
    }

    QQC2.Label {
        Layout.fillWidth: true
        wrapMode: Text.WordWrap
        opacity: 0.7
        text: "Speeds are for the whole PC. Per-program speeds in the popup are TCP only: games mostly use UDP, which the kernel does not count. These settings only affect the widget when it sits in a panel; on the desktop it always shows the full view."
    }
}
