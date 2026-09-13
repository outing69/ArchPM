import QtCore
import QtQuick
import QtQuick.Layouts
import org.kde.plasma.plasmoid
import org.kde.plasma.core as PlasmaCore
import org.kde.plasma.plasma5support as P5Support
import org.kde.kirigami as Kirigami

PlasmoidItem {
    id: root

    // The agent writes to $XDG_RUNTIME_DIR/archpm/status.json and puts a symlink
    // to it in ~/.cache/archpm/ -- that path is predictable from QML.
    //
    // Reading goes through the executable data engine, not XMLHttpRequest: Qt 6
    // blocks XHR on file:// unless QML_XHR_ALLOW_FILE_READ is set, and that
    // is an environment variable for all of plasmashell -- we do not set it.
    readonly property string statusFile:
        StandardPaths.writableLocation(StandardPaths.GenericCacheLocation)
            .toString().replace("file://", "") + "/archpm/status.json"
    readonly property string readCommand: "cat '" + statusFile + "'"

    property var stats: ({})
    property bool online: false
    property int misses: 0

    // At most 32 bars in the core strip; bigger CPUs are shown as group averages.
    readonly property var coreBars: root.groupCores(root.stats.cores || [], 32)

    function groupCores(cores, maxBars) {
        if (cores.length <= maxBars)
            return cores
        var per = Math.ceil(cores.length / maxBars)
        var out = []
        for (var i = 0; i < cores.length; i += per) {
            var sum = 0, n = 0
            for (var j = i; j < Math.min(i + per, cores.length); j++) { sum += cores[j]; n++ }
            out.push(sum / n)
        }
        return out
    }

    readonly property color cpuColor: "#4c8dff"
    readonly property color gpuColor: "#9b7dff"
    readonly property color memColor: "#f2a65a"
    readonly property color vramColor: "#e2749c"

    preferredRepresentation: fullRepresentation
    Plasmoid.backgroundHints: PlasmaCore.Types.DefaultBackground | PlasmaCore.Types.ConfigurableBackground

    Layout.minimumWidth: Kirigami.Units.gridUnit * 13
    Layout.minimumHeight: Kirigami.Units.gridUnit * 16
    Layout.preferredWidth: Kirigami.Units.gridUnit * 15
    Layout.preferredHeight: Kirigami.Units.gridUnit * 20

    function accept(text) {
        if (!text || text.length < 3) {
            root.miss()
            return
        }
        try {
            var parsed = JSON.parse(text)
        } catch (e) {
            // Half-written file or garbage: simply retry next tick.
            root.miss()
            return
        }
        root.stats = parsed
        // Older than 15 s? Then the agent has stopped writing.
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
            // Disconnect immediately, otherwise the engine refuses the same source again.
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

    Timer {
        interval: 2000
        running: true
        repeat: true
        triggeredOnStart: true
        onTriggered: reader.poll()
    }

    function fmtBytes(n) {
        var units = ["B", "K", "M", "G", "T"]
        var i = 0
        while (n >= 1024 && i < units.length - 1) { n /= 1024; i++ }
        return (i === 0 ? n.toFixed(0) : n.toFixed(1)) + " " + units[i]
    }

    fullRepresentation: Item {
        Layout.minimumWidth: Kirigami.Units.gridUnit * 13
        Layout.minimumHeight: Kirigami.Units.gridUnit * 16

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: Kirigami.Units.smallSpacing * 2
            spacing: Kirigami.Units.smallSpacing * 1.5

            // -- header ---------------------------------------------------
            RowLayout {
                Layout.fillWidth: true
                Kirigami.Heading {
                    text: "ArchPM"
                    level: 5
                    Layout.fillWidth: true
                }
                Rectangle {
                    width: Kirigami.Units.gridUnit * 0.4
                    height: width
                    radius: width / 2
                    color: root.online ? "#59d98e" : "#ff5f6d"
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

            // -- meters ---------------------------------------------------
            Bar {
                Layout.fillWidth: true
                label: "CPU"
                accent: root.cpuColor
                value: root.stats.cpu || 0
                text: (root.stats.cpu || 0).toFixed(0) + "%"
                      + (root.stats.cpu_temp ? "  " + root.stats.cpu_temp.toFixed(0) + "°" : "")
            }

            // core strip: shows whether a game only uses a few threads
            Row {
                Layout.fillWidth: true
                spacing: 2
                visible: root.coreBars.length > 0
                Repeater {
                    model: root.coreBars
                    Rectangle {
                        width: (parent.width - (parent.spacing * (root.coreBars.length - 1)))
                               / Math.max(1, root.coreBars.length)
                        height: Kirigami.Units.gridUnit
                        radius: 2
                        color: Kirigami.Theme.textColor
                        opacity: 0.13
                        Rectangle {
                            anchors.bottom: parent.bottom
                            width: parent.width
                            radius: 2
                            height: Math.max(1, parent.height * Math.min(1, modelData / 100))
                            color: modelData > 85 ? "#ff5f6d" : (modelData > 60 ? "#ffb454" : "#59d98e")
                        }
                    }
                }
            }

            Bar {
                Layout.fillWidth: true
                label: "GPU"
                accent: root.gpuColor
                visible: root.stats.gpu !== undefined
                value: root.stats.gpu ? root.stats.gpu.util : 0
                text: root.stats.gpu
                      ? root.stats.gpu.util.toFixed(0) + "%  " + root.stats.gpu.temp.toFixed(0) + "°"
                      : ""
            }
            Bar {
                Layout.fillWidth: true
                label: "VRAM"
                accent: root.vramColor
                visible: root.stats.gpu !== undefined
                value: root.stats.gpu ? root.stats.gpu.mem_pct : 0
                text: root.stats.gpu
                      ? (root.stats.gpu.mem_used / 1024).toFixed(1) + " / "
                        + (root.stats.gpu.mem_total / 1024).toFixed(0) + " G"
                      : ""
            }
            Bar {
                Layout.fillWidth: true
                label: "RAM"
                accent: root.memColor
                value: root.stats.mem_pct || 0
                text: root.fmtBytes(root.stats.mem_used || 0) + " / "
                      + root.fmtBytes(root.stats.mem_total || 0)
            }

            Rectangle {
                Layout.fillWidth: true
                height: 1
                color: Kirigami.Theme.textColor
                opacity: 0.12
            }

            // -- heaviest processes --------------------------------------
            Item { implicitHeight: Kirigami.Units.smallSpacing }

            Text {
                text: "TOP PROCESSES"
                color: Kirigami.Theme.textColor
                opacity: 0.55
                font.pointSize: Kirigami.Theme.smallFont.pointSize - 1
                font.bold: true
            }
            Repeater {
                model: root.stats.top_cpu || []
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
                    Text {
                        text: modelData.v.toFixed(0) + "%"
                        color: Kirigami.Theme.textColor
                        opacity: 0.7
                        font.family: "monospace"
                        font.pointSize: Kirigami.Theme.smallFont.pointSize
                    }
                }
            }

            Item { Layout.fillHeight: true }

            Rectangle {
                Layout.fillWidth: true
                height: 1
                color: Kirigami.Theme.textColor
                opacity: 0.12
            }

            // -- footer ----------------------------------------------------
            RowLayout {
                Layout.fillWidth: true
                Text {
                    Layout.fillWidth: true
                    color: Kirigami.Theme.textColor
                    opacity: 0.55
                    font.pointSize: Kirigami.Theme.smallFont.pointSize - 1
                    text: "↓ " + root.fmtBytes(root.stats.net_rx || 0) + "/s   ↑ "
                          + root.fmtBytes(root.stats.net_tx || 0) + "/s"
                }
                Text {
                    color: Kirigami.Theme.textColor
                    opacity: 0.55
                    font.pointSize: Kirigami.Theme.smallFont.pointSize - 1
                    text: (root.stats.procs || 0) + " proc"
                }
            }
        }
    }

    // In the panel: compact text representation.
    compactRepresentation: RowLayout {
        spacing: Kirigami.Units.smallSpacing
        Text {
            text: "C " + (root.stats.cpu || 0).toFixed(0) + "%"
            color: root.cpuColor
            font.family: "monospace"
        }
        Text {
            visible: root.stats.gpu !== undefined
            text: "G " + (root.stats.gpu ? root.stats.gpu.util.toFixed(0) : 0) + "%"
            color: root.gpuColor
            font.family: "monospace"
        }
    }
}
