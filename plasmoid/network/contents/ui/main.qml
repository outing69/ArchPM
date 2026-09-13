import QtCore
import QtQuick
import QtQuick.Layouts
import org.kde.plasma.plasmoid
import org.kde.plasma.core as PlasmaCore
import org.kde.plasma.plasma5support as P5Support
import org.kde.kirigami as Kirigami

// ArchPM Network: the network half of the agent's status file. Same file, same
// reader as the ArchPM Monitor widget; see that one for why the executable
// data engine is used instead of XMLHttpRequest.
PlasmoidItem {
    id: root

    readonly property string statusFile:
        StandardPaths.writableLocation(StandardPaths.GenericCacheLocation)
            .toString().replace("file://", "") + "/archpm/status.json"
    readonly property string readCommand: "cat '" + statusFile + "'"

    property var stats: ({})
    property bool online: false
    property int misses: 0

    readonly property var net: root.stats.net || null
    readonly property var ifaces: root.net ? (root.net.ifaces || []) : []
    readonly property var talkers: root.net ? (root.net.top || []) : []
    readonly property var doors: root.net ? (root.net.listening || []) : []
    readonly property bool vpnUp: root.ifaces.some(function (i) { return i.vpn && i.up })
    readonly property bool showVpn: Plasmoid.configuration.showVpn
    readonly property bool showTop: Plasmoid.configuration.showTop

    readonly property color downColor: "#5aa2ff"
    readonly property color upColor: "#4fd1c5"
    readonly property color vpnColor: "#59d98e"
    readonly property color doorColor: "#f5a524"
    readonly property color hotColor: "#ff5f6d"

    function fmtBytes(n) {
        var units = ["B", "KB", "MB", "GB", "TB"]
        var i = 0
        while (n >= 1024 && i < units.length - 1) { n /= 1024; i++ }
        return (i === 0 ? n.toFixed(0) : n.toFixed(1)) + " " + units[i]
    }
    function rate(n) { return root.fmtBytes(n || 0) + "/s" }
    function shellQuote(s) { return "'" + String(s).replace(/'/g, "'\\''") + "'" }
    function openArchPM() {
        if (!root.stats.launch) return
        launcher.connectSource("setsid -f sh -c " + shellQuote(root.stats.launch) + " >/dev/null 2>&1")
    }

    readonly property bool inPanel: Plasmoid.formFactor === PlasmaCore.Types.Horizontal
                                    || Plasmoid.formFactor === PlasmaCore.Types.Vertical
    preferredRepresentation: inPanel ? compactRepresentation : fullRepresentation
    Plasmoid.backgroundHints: PlasmaCore.Types.DefaultBackground | PlasmaCore.Types.ConfigurableBackground

    Layout.minimumWidth: Kirigami.Units.gridUnit * 14
    Layout.minimumHeight: Kirigami.Units.gridUnit * 14
    Layout.preferredWidth: Kirigami.Units.gridUnit * 16
    Layout.preferredHeight: Kirigami.Units.gridUnit * 18

    function accept(text) {
        if (!text || text.length < 3) {
            root.miss()
            return
        }
        try {
            var parsed = JSON.parse(text)
        } catch (e) {
            root.miss()
            return
        }
        root.stats = parsed
        root.online = (Date.now() / 1000 - (parsed.ts || 0)) < 15
        root.misses = 0
    }

    function miss() {
        root.misses++
        if (root.misses > 2)
            root.online = false
    }

    P5Support.DataSource {
        id: reader
        engine: "executable"
        connectedSources: []
        onNewData: function (source, data) {
            disconnectSource(source)
            if (data["exit code"] === 0)
                root.accept(data.stdout)
            else
                root.miss()
        }
        function poll() {
            disconnectSource(root.readCommand)
            connectSource(root.readCommand)
        }
    }

    P5Support.DataSource {
        id: launcher
        engine: "executable"
        connectedSources: []
        onNewData: function (source, data) { disconnectSource(source) }
    }

    Timer {
        interval: 2000
        running: true
        repeat: true
        triggeredOnStart: true
        onTriggered: reader.poll()
    }

    component Section: Text {
        color: Kirigami.Theme.textColor
        opacity: 0.55
        font.pointSize: Kirigami.Theme.smallFont.pointSize - 1
        font.bold: true
    }
    component Mono: Text {
        color: Kirigami.Theme.textColor
        font.family: "monospace"
        font.pointSize: Kirigami.Theme.smallFont.pointSize
    }
    component Rule: Rectangle {
        Layout.fillWidth: true
        height: 1
        color: Kirigami.Theme.textColor
        opacity: 0.12
    }

    fullRepresentation: Item {
        Layout.minimumWidth: Kirigami.Units.gridUnit * 14
        Layout.minimumHeight: Kirigami.Units.gridUnit * 14

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: Kirigami.Units.smallSpacing * 2
            spacing: Kirigami.Units.smallSpacing * 1.5

            RowLayout {
                Layout.fillWidth: true
                Kirigami.Heading {
                    text: "Network"
                    level: 5
                    Layout.fillWidth: true
                }
                Text {
                    text: "Open ArchPM"
                    visible: !!root.stats.launch
                    color: "#f5c542"
                    font: Kirigami.Theme.smallFont
                    MouseArea {
                        anchors.fill: parent
                        cursorShape: Qt.PointingHandCursor
                        onClicked: root.openArchPM()
                    }
                }
                Rectangle {
                    width: Kirigami.Units.gridUnit * 0.4
                    height: width
                    radius: width / 2
                    color: root.online ? root.vpnColor : root.hotColor
                    opacity: root.online ? 1 : 0.8
                }
            }

            Text {
                visible: !root.online
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
                color: Kirigami.Theme.textColor
                opacity: 0.7
                font: Kirigami.Theme.smallFont
                text: "No data. Start the agent:\nsystemctl --user start archpm-agent"
            }

            // -- whole PC --------------------------------------------------
            RowLayout {
                Layout.fillWidth: true
                spacing: Kirigami.Units.largeSpacing
                Mono {
                    text: "↓ " + root.rate(root.stats.net_rx)
                    color: root.downColor
                    font.pointSize: Kirigami.Theme.defaultFont.pointSize + 1
                    font.bold: true
                }
                Mono {
                    text: "↑ " + root.rate(root.stats.net_tx)
                    color: root.upColor
                    font.pointSize: Kirigami.Theme.defaultFont.pointSize + 1
                    font.bold: true
                }
                Item { Layout.fillWidth: true }
                Text {
                    visible: root.vpnUp
                    text: "VPN"
                    color: root.vpnColor
                    font.bold: true
                    font.pointSize: Kirigami.Theme.smallFont.pointSize
                }
            }

            // -- interfaces -----------------------------------------------
            Section { text: "INTERFACES" }
            Repeater {
                model: root.ifaces
                RowLayout {
                    Layout.fillWidth: true
                    visible: modelData.up
                    spacing: Kirigami.Units.smallSpacing
                    Mono {
                        text: modelData.name
                        color: modelData.vpn ? root.vpnColor : Kirigami.Theme.textColor
                        font.bold: true
                    }
                    Text {
                        text: modelData.vpn ? "VPN" : (modelData.addr || "")
                        color: Kirigami.Theme.textColor
                        opacity: 0.55
                        font: Kirigami.Theme.smallFont
                        elide: Text.ElideRight
                        Layout.fillWidth: true
                    }
                    Mono { text: "↓ " + root.rate(modelData.rx); color: root.downColor }
                    Mono { text: "↑ " + root.rate(modelData.tx); color: root.upColor }
                }
            }
            Rule {}

            // -- top talkers -----------------------------------------------
            Section { text: "USING THE NETWORK (TCP)" }
            Text {
                visible: root.talkers.length === 0
                color: Kirigami.Theme.textColor
                opacity: 0.55
                font: Kirigami.Theme.smallFont
                text: root.net && !root.net.tcp_rates ? "ss not found: no per-program speeds"
                                                      : "Nothing above 1 KB/s right now"
            }
            Repeater {
                model: root.talkers
                RowLayout {
                    Layout.fillWidth: true
                    spacing: Kirigami.Units.smallSpacing
                    Text {
                        text: modelData.name
                        color: Kirigami.Theme.textColor
                        font: Kirigami.Theme.smallFont
                        elide: Text.ElideRight
                        Layout.fillWidth: true
                    }
                    Mono { text: "↓ " + root.rate(modelData.rx); color: root.downColor; opacity: 0.85 }
                    Mono { text: "↑ " + root.rate(modelData.tx); color: root.upColor; opacity: 0.85 }
                }
            }
            Rule {}

            // -- open doors --------------------------------------------------
            Section { text: "OPEN DOORS" }
            Text {
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
                color: Kirigami.Theme.textColor
                opacity: 0.55
                font: Kirigami.Theme.smallFont
                text: root.doors.length === 0
                      ? "No program accepts connections from other devices."
                      : "Reachable from other devices on your network:"
            }
            Repeater {
                model: root.doors
                RowLayout {
                    Layout.fillWidth: true
                    spacing: Kirigami.Units.smallSpacing
                    Text {
                        text: modelData.name
                        color: root.doorColor
                        font: Kirigami.Theme.smallFont
                        elide: Text.ElideRight
                        Layout.fillWidth: true
                    }
                    Mono {
                        text: "port " + (modelData.ports || []).join(", ")
                        opacity: 0.7
                    }
                }
            }

            Item { Layout.fillHeight: true }
            Rule {}
            Text {
                Layout.fillWidth: true
                color: Kirigami.Theme.textColor
                opacity: 0.55
                font.pointSize: Kirigami.Theme.smallFont.pointSize - 1
                text: (root.net ? root.net.connections : 0) + " connections open"
            }
        }
    }

    // In the panel: download and upload of the whole PC, "VPN" while a tunnel
    // is up, optionally the busiest program. Click for the full view.
    compactRepresentation: MouseArea {
        id: compact
        Layout.minimumWidth: strip.implicitWidth + Kirigami.Units.smallSpacing * 2
        Layout.preferredWidth: Layout.minimumWidth
        onClicked: root.expanded = !root.expanded
        hoverEnabled: true

        RowLayout {
            id: strip
            anchors.centerIn: parent
            spacing: Kirigami.Units.smallSpacing

            Rectangle {
                width: Kirigami.Units.gridUnit * 0.35
                height: width
                radius: width / 2
                color: root.hotColor
                visible: !root.online
            }
            Mono { text: "↓ " + root.rate(root.stats.net_rx); color: root.downColor }
            Mono { text: "↑ " + root.rate(root.stats.net_tx); color: root.upColor }
            Text {
                visible: root.showVpn && root.vpnUp
                text: "VPN"
                color: root.vpnColor
                font.bold: true
                font.pointSize: Kirigami.Theme.smallFont.pointSize
            }
            Text {
                visible: root.showTop && root.talkers.length > 0
                text: "· " + (root.talkers.length > 0 ? root.talkers[0].name : "")
                color: Kirigami.Theme.textColor
                opacity: 0.7
                font.pointSize: Kirigami.Theme.smallFont.pointSize
                elide: Text.ElideRight
                Layout.maximumWidth: Kirigami.Units.gridUnit * 10
            }
        }
    }
}
