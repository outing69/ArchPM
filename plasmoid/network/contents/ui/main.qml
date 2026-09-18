import QtCore
import QtQuick
import QtQuick.Controls as QQC2
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
    // The column's form of a rate: no spaces, the unit's first letter, per
    // second understood, a decimal only under 10, the next unit from 1000,
    // so at most four characters ("999K", "1.2M") and five with the arrow.
    function shortRate(n) {
        n = n || 0
        var units = ["B", "K", "M", "G", "T"]
        var i = 0
        while (n >= 1000 && i < units.length - 1) { n /= 1024; i++ }
        return (i > 0 && n < 10 ? n.toFixed(1) : n.toFixed(0)) + units[i]
    }
    // How ArchPM is started: fixed at install time, see the Monitor widget.
    readonly property string launchTemplate: "@LAUNCH@"
    readonly property string launchCommand:
        launchTemplate.charAt(0) === "@" ? "archpm" : launchTemplate
    function openArchPM() {
        launcher.connectSource("setsid -f " + root.launchCommand + " >/dev/null 2>&1")
    }

    readonly property bool inPanel: Plasmoid.formFactor === PlasmaCore.Types.Horizontal
                                    || Plasmoid.formFactor === PlasmaCore.Types.Vertical
    preferredRepresentation: inPanel ? compactRepresentation : fullRepresentation
    Plasmoid.backgroundHints: PlasmaCore.Types.DefaultBackground | PlasmaCore.Types.ConfigurableBackground
    // The tooltip of the strip: the rates in full, since a vertical panel
    // shows them short.
    toolTipMainText: "Network"
    toolTipSubText: root.online
                    ? "Download " + root.rate(root.stats.net_rx) + ", upload " + root.rate(root.stats.net_tx)
                    : "No data. Start the agent: systemctl --user start archpm-agent"

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
    // A program's name: elides when the row is narrow, with the full name
    // in a tooltip while it is elided.
    component Name: Text {
        color: Kirigami.Theme.textColor
        font: Kirigami.Theme.smallFont
        elide: Text.ElideRight
        HoverHandler { id: hover }
        QQC2.ToolTip.visible: hover.hovered && truncated
        QQC2.ToolTip.text: text
        QQC2.ToolTip.delay: 400
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
            // Each interface is a Flow, not a row: the name, the address and
            // the two rates follow one another and go on to the next line
            // when the widget is narrow, so the address is never cut and no
            // row is ever wider than the widget.
            Repeater {
                model: root.ifaces
                Flow {
                    Layout.fillWidth: true
                    visible: modelData.up
                    spacing: Kirigami.Units.smallSpacing * 2
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
                    Name {
                        text: modelData.name
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
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
            // A door is a Flow too: the name elides only when it alone is
            // wider than the widget, and the port list wraps like a sentence.
            Repeater {
                model: root.doors
                Flow {
                    id: door
                    Layout.fillWidth: true
                    spacing: Kirigami.Units.smallSpacing * 2
                    Name {
                        text: modelData.name
                        color: root.doorColor
                        width: Math.min(implicitWidth, door.width)
                    }
                    Mono {
                        text: "port " + (modelData.ports || []).join(", ")
                        opacity: 0.7
                        wrapMode: Text.WordWrap
                        width: Math.min(implicitWidth, door.width)
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

    // In the panel: download and upload of the whole PC on one line, an
    // arrow and a rate each, nothing else; a click opens the full view. Each
    // rate has the width of its widest form ("↓ 1023.9 MB/s") reserved, so
    // the strip keeps one width while the numbers change every two seconds.
    // A vertical panel is a column too narrow for that line: there the two
    // rates stack, in the short form ("↓1.2M", "↑88K"; the tooltip says it in full),
    // at a size fitted once to the column for that form's widest case, so
    // the size does not change with the value either. The colours are the
    // theme's text colour; no data dims the line.
    compactRepresentation: MouseArea {
        id: compact
        readonly property bool vertical: Plasmoid.formFactor === PlasmaCore.Types.Vertical
        readonly property real pad: Kirigami.Units.smallSpacing
        readonly property real gap: Kirigami.Units.smallSpacing * 2
        readonly property real smallPt: Kirigami.Theme.smallFont.pointSize

        TextMetrics {
            id: widest
            font.family: "monospace"
            font.pointSize: compact.smallPt
            text: "↓ 1023.9 MB/s"
        }
        TextMetrics {
            id: widestShort
            font.family: "monospace"
            font.pointSize: compact.smallPt
            text: "↓999M"
        }
        readonly property int cell: Math.ceil(widest.advanceWidth)
        readonly property real columnWidth: Math.max(1, width - 2 * pad)
        // the column's font: the small font, or smaller when the widest short
        // form would not fit the column at that size; never below 5 pt
        readonly property real columnPt: Math.max(5, Math.min(smallPt,
            smallPt * columnWidth / Math.max(1, widestShort.advanceWidth)))
        readonly property real stripWidth: cell * 2 + gap + pad * 2
        readonly property real stackHeight: widest.height * 2 + pad * 2

        Layout.fillWidth: vertical
        Layout.fillHeight: !vertical
        Layout.minimumWidth: vertical ? 0 : stripWidth
        Layout.preferredWidth: vertical ? 0 : stripWidth
        Layout.minimumHeight: vertical ? stackHeight : 0
        Layout.preferredHeight: vertical ? stackHeight : 0
        hoverEnabled: true
        onClicked: root.expanded = !root.expanded

        component Rate: Text {
            property string arrow
            property real value: 0
            color: Kirigami.Theme.textColor
            opacity: root.online ? 1 : 0.5
            font.family: "monospace"
            font.pointSize: compact.vertical ? compact.columnPt : compact.smallPt
            text: compact.vertical ? arrow + root.shortRate(value) : arrow + " " + root.rate(value)
            horizontalAlignment: compact.vertical ? Text.AlignHCenter : Text.AlignLeft
            verticalAlignment: Text.AlignVCenter
            Layout.preferredWidth: compact.vertical ? compact.columnWidth : compact.cell
            Layout.minimumWidth: Layout.preferredWidth
            Layout.maximumWidth: Layout.preferredWidth
        }

        GridLayout {
            id: strip
            anchors.centerIn: parent
            columns: compact.vertical ? 1 : 2
            columnSpacing: compact.gap
            rowSpacing: 0
            Rate { arrow: "↓"; value: root.stats.net_rx || 0 }
            Rate { arrow: "↑"; value: root.stats.net_tx || 0 }
        }
    }
}
