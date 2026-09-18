import QtCore
import QtQuick
import QtQuick.Controls as QQC2
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
    readonly property color hotColor: "#ff5f6d"
    // Where the application itself calls a part busy, full or hot, so the
    // panel strip agrees with the window: archpm/verdict.py's MACHINE_BUSY,
    // GAME_GPU_FULL, MEM_FULL_PCT and HOT_C. A test holds them together.
    readonly property real busyPct: 85
    readonly property real gpuFullPct: 85
    readonly property real memFullPct: 85
    readonly property real hotC: 90

    // Panel strip settings (right-click -> Configure): 0 percentages, 1 temperatures, 2 both
    readonly property int panelMode: Plasmoid.configuration.panelMode
    readonly property bool showGame: Plasmoid.configuration.showGame
    readonly property var game: root.stats.game || null

    function pct(v) { return (v || 0).toFixed(0) + "%" }
    function deg(v) { return (v || 0).toFixed(0) + "°" }
    function cpuText() {
        var c = root.stats.cpu, t = root.stats.cpu_temp
        if (root.panelMode === 1) return deg(t)
        if (root.panelMode === 2) return pct(c) + " " + deg(t)
        return pct(c)
    }
    function gpuText() {
        if (!root.stats.gpu) return ""
        var g = root.stats.gpu
        if (root.panelMode === 1) return deg(g.temp)
        if (root.panelMode === 2) return pct(g.util) + " " + deg(g.temp)
        return pct(g.util)
    }
    // How ArchPM is started: a command fixed when the widget is installed
    // (install.sh and the PKGBUILD fill in the placeholder), never anything
    // read from status.json. An unrendered copy, as from kpackagetool6 on the
    // checkout, falls back to "archpm" on PATH.
    readonly property string launchTemplate: "@LAUNCH@"
    readonly property string launchCommand:
        launchTemplate.charAt(0) === "@" ? "archpm" : launchTemplate

    // setsid detaches the window from the data engine, which would otherwise
    // wait for it to exit. The single-instance socket raises an open window.
    function openArchPM() {
        launcher.connectSource("setsid -f " + root.launchCommand + " >/dev/null 2>&1")
    }
    // "End game" hands the request to ArchPM: the window asks, runs its
    // signal guard and sends, exactly as from its own button. The widget
    // sends no signal itself and takes no pid from the file.
    function endGame() {
        launcher.connectSource("setsid -f " + root.launchCommand + " --end-game >/dev/null 2>&1")
    }

    // In a panel (horizontal or vertical form factor) show the strip and open
    // the full view as a popup; on the desktop show the full view itself.
    readonly property bool inPanel: Plasmoid.formFactor === PlasmaCore.Types.Horizontal
                                    || Plasmoid.formFactor === PlasmaCore.Types.Vertical
    preferredRepresentation: inPanel ? compactRepresentation : fullRepresentation
    Plasmoid.backgroundHints: PlasmaCore.Types.DefaultBackground | PlasmaCore.Types.ConfigurableBackground
    // The tooltip of the strip: the figures in words, since the icons no
    // longer say what a number is.
    toolTipMainText: "ArchPM"
    toolTipSubText: {
        if (!root.online)
            return "No data. Start the agent: systemctl --user start archpm-agent"
        var parts = ["Processor " + root.pct(root.stats.cpu)
                     + (root.stats.cpu_temp ? " at " + root.deg(root.stats.cpu_temp) : "")]
        if (root.stats.gpu)
            parts.push("graphics card " + root.pct(root.stats.gpu.util) + " at " + root.deg(root.stats.gpu.temp))
        parts.push("memory " + root.pct(root.stats.mem_pct) + " (" + root.fmtBytes(root.stats.mem_used || 0)
                   + " of " + root.fmtBytes(root.stats.mem_total || 0) + ")")
        var text = parts.join(", ")
        if (root.game)
            text += "\nGame: " + root.game.name
        return text
    }

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

    function fmtBytes(n) {
        var units = ["B", "KB", "MB", "GB", "TB"]
        var i = 0
        while (n >= 1024 && i < units.length - 1) { n /= 1024; i++ }
        return (i === 0 ? n.toFixed(0) : n.toFixed(1)) + " " + units[i]
    }

    // A list that shows only the rows that fit whole in the height it is
    // given: the rows in order, each shown while it and the ones before it
    // fit, the rest not shown at all, so never a half row. In the column it
    // takes what its rows need and no more, gives way first when the widget
    // is short, and leaves the footer where it is.
    component FitList: Item {
        id: fitList
        property alias model: rep.model
        property alias delegate: rep.delegate
        property int spacing: Kirigami.Units.smallSpacing
        property int revision: 0        // bumped when a row appears, goes or changes height
        readonly property int count: rep.count
        readonly property int shown: fitList.fit(rep.count, height, revision)
        // the height of every row, shown or not: what the list asks the
        // column for (its need depends on the rows, never on the height it
        // gets, or the two would chase each other)
        readonly property real contentHeight: fitList.need(rep.count, revision)
        function need(n, _rev) {
            var total = 0
            for (var i = 0; i < n; i++) {
                var row = rep.itemAt(i)
                if (row)
                    total += row.implicitHeight + (i > 0 ? spacing : 0)
            }
            return total
        }
        function fit(n, h, _rev) {
            var used = 0
            for (var i = 0; i < n; i++) {
                var row = rep.itemAt(i)
                if (!row)
                    return i
                used += row.implicitHeight + (i > 0 ? spacing : 0)
                if (used > h + 0.5)
                    return i
            }
            return n
        }
        clip: true
        implicitHeight: contentHeight
        Layout.fillWidth: true
        Layout.fillHeight: true
        Layout.minimumHeight: 0
        Layout.preferredHeight: contentHeight
        Layout.maximumHeight: contentHeight
        Column {
            id: rows
            width: parent.width
            spacing: fitList.spacing
            Repeater {
                id: rep
                onItemAdded: function (i, item) {
                    item.width = Qt.binding(function () { return rows.width })
                    item.visible = Qt.binding(function () { return i < fitList.shown })
                    item.implicitHeightChanged.connect(function () { fitList.revision++ })
                    fitList.revision++
                }
                onItemRemoved: fitList.revision++
            }
        }
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
                Text {
                    // acts as a link: the app opens, or comes to the front
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

            // -- the running game ------------------------------------------
            ColumnLayout {
                Layout.fillWidth: true
                visible: root.game !== null
                spacing: 1
                RowLayout {
                    Layout.fillWidth: true
                    Text {
                        Layout.fillWidth: true
                        elide: Text.ElideRight
                        text: root.game ? root.game.name : ""
                        color: "#f5c542"
                        font.bold: true
                        font.pointSize: Kirigami.Theme.smallFont.pointSize
                        HoverHandler { id: gameHover }
                        QQC2.ToolTip.visible: gameHover.hovered && truncated
                        QQC2.ToolTip.text: text
                        QQC2.ToolTip.delay: 400
                    }
                    // Ends the game through ArchPM: the window comes to the
                    // front and asks first, so one click is enough here.
                    Text {
                        text: "End game…"
                        color: root.hotColor
                        font.pointSize: Kirigami.Theme.smallFont.pointSize
                        MouseArea {
                            anchors.fill: parent
                            cursorShape: Qt.PointingHandCursor
                            onClicked: root.endGame()
                        }
                    }
                }
                Text {
                    Layout.fillWidth: true
                    wrapMode: Text.WordWrap      // a narrow widget: two lines, never cut
                    color: Kirigami.Theme.textColor
                    opacity: 0.7
                    font.family: "monospace"
                    font.pointSize: Kirigami.Theme.smallFont.pointSize - 1
                    text: root.game
                          ? "GPU " + root.pct(root.game.gpu) + "  ·  " + root.game.cores.toFixed(1) + " cores  ·  VRAM "
                            + (root.game.vram / 1024).toFixed(1) + " GB  ·  " + root.game.procs + " proc"
                          : ""
                }
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
                    // Track and fill are siblings: a child would inherit the
                    // track's 0.13 opacity and the fill would look washed out.
                    Item {
                        width: (parent.width - (parent.spacing * (root.coreBars.length - 1)))
                               / Math.max(1, root.coreBars.length)
                        height: Kirigami.Units.gridUnit
                        Rectangle {
                            anchors.fill: parent
                            radius: 2
                            color: Kirigami.Theme.textColor
                            opacity: 0.13
                        }
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
                        + (root.stats.gpu.mem_total / 1024).toFixed(0) + " GB"
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
                visible: topList.shown > 0
                text: "TOP PROCESSES"
                color: Kirigami.Theme.textColor
                opacity: 0.55
                font.pointSize: Kirigami.Theme.smallFont.pointSize - 1
                font.bold: true
            }
            // As many of the heaviest processes as fit whole above the
            // footer; the publisher sends five, a short widget shows fewer.
            FitList {
                id: topList
                model: root.stats.top_cpu || []
                spacing: Kirigami.Units.smallSpacing * 1.5
                delegate: RowLayout {
                    spacing: Kirigami.Units.smallSpacing
                    Text {
                        text: modelData.name
                        color: Kirigami.Theme.textColor
                        font: Kirigami.Theme.smallFont
                        elide: Text.ElideRight
                        Layout.fillWidth: true
                        HoverHandler { id: nameHover }
                        QQC2.ToolTip.visible: nameHover.hovered && truncated
                        QQC2.ToolTip.text: text
                        QQC2.ToolTip.delay: 400
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

    // In the panel: three meters, each a theme icon (the processor, the
    // graphics card, the memory), a thin vertical bar and the number, in the
    // theme's colours; the bar fills with the theme's highlight and turns
    // to its negative colour where the application itself calls the part
    // busy or full, a temperature turns negative where it calls it hot.
    // Each number has the width of its widest form reserved ("100%", or
    // "100°", or "100% 100°" by the panel setting), so nothing moves with
    // a value. A vertical panel is a narrow column: there each meter is the
    // icon over the number over a thin horizontal bar. The game's name, by
    // its setting, stays in front. A click opens the full view.
    compactRepresentation: MouseArea {
        id: compact
        readonly property bool vertical: Plasmoid.formFactor === PlasmaCore.Types.Vertical
        readonly property real pad: Kirigami.Units.smallSpacing
        readonly property real gap: Kirigami.Units.smallSpacing
        readonly property real smallPt: Kirigami.Theme.smallFont.pointSize
        readonly property int iconSize: Kirigami.Units.iconSizes.small
        readonly property int barThickness: 3
        readonly property bool withPct: root.panelMode !== 1
        readonly property bool withTemp: root.panelMode !== 0
        // the widest form a number takes in this panel setting
        readonly property string widestText: root.panelMode === 1 ? "100°"
                                             : root.panelMode === 2 ? "100% 100°" : "100%"

        TextMetrics {
            id: widest
            font.family: "monospace"
            font.pointSize: compact.smallPt
            text: compact.widestText
        }
        readonly property int cell: Math.ceil(widest.advanceWidth)
        readonly property int lineH: Math.ceil(widest.height)
        // one meter across: icon, bar, number, with a gap between each
        readonly property real meterWidth: iconSize + gap + (withPct ? barThickness + gap : 0) + cell
        readonly property int meters: root.stats.gpu !== undefined ? 3 : 2
        readonly property real stripWidth: meters * meterWidth + (meters - 1) * gap * 2 + pad * 2
                                           + (gameLabel.visible ? gameLabel.width + gap * 2 : 0)
        // one meter down, in a column: icon over number over bar
        readonly property real meterHeight: iconSize + lineH + (withPct ? barThickness + 2 : 0)
        readonly property real stackHeight: meters * meterHeight + (meters - 1) * gap * 2 + pad * 2

        Layout.fillWidth: vertical
        Layout.fillHeight: !vertical
        Layout.minimumWidth: vertical ? 0 : stripWidth
        Layout.preferredWidth: vertical ? 0 : stripWidth
        Layout.minimumHeight: vertical ? stackHeight : 0
        Layout.preferredHeight: vertical ? stackHeight : 0
        hoverEnabled: true
        onClicked: root.expanded = !root.expanded

        // One meter: the icon, the bar and the number; across in a panel,
        // stacked in a column. The icon is the theme's, with a fallback name
        // from the freedesktop set for a theme that lacks the first; when
        // both are missing Kirigami paints its "unknown" placeholder, so the
        // slot is never blank. It is drawn as a mask in the text colour.
        component Meter: GridLayout {
            id: meter
            property string icon
            property string iconFallback
            property real value: 0        // the percentage, 0..100
            property real temp: 0         // degrees, 0 when unknown
            property real limit: 100      // where the application calls it busy or full
            property bool isPct: true
            readonly property bool high: value >= limit
            readonly property bool hot: temp >= root.hotC
            readonly property color fill: high ? Kirigami.Theme.negativeTextColor : Kirigami.Theme.highlightColor
            readonly property string label: root.panelMode === 1 ? root.deg(temp)
                                            : root.panelMode === 2 ? root.pct(value) + " " + root.deg(temp)
                                            : root.pct(value)
            columns: compact.vertical ? 1 : 3
            rowSpacing: compact.vertical ? 2 : 0
            columnSpacing: compact.gap
            opacity: root.online ? 1 : 0.5

            Kirigami.Icon {
                source: meter.icon
                fallback: meter.iconFallback
                isMask: true
                color: Kirigami.Theme.textColor
                Layout.preferredWidth: compact.iconSize
                Layout.preferredHeight: compact.iconSize
                Layout.alignment: Qt.AlignCenter
            }
            // across: the thin vertical bar, the height of the text
            Item {
                visible: !compact.vertical && compact.withPct
                Layout.preferredWidth: compact.barThickness
                Layout.preferredHeight: compact.lineH
                Layout.alignment: Qt.AlignCenter
                Rectangle { anchors.fill: parent; radius: width / 2; color: Kirigami.Theme.textColor; opacity: 0.25 }
                Rectangle {
                    anchors.bottom: parent.bottom
                    width: parent.width
                    radius: width / 2
                    height: Math.max(width, parent.height * Math.max(0, Math.min(1, meter.value / 100)))
                    color: meter.fill
                }
            }
            Text {
                text: meter.label
                color: (meter.hot && compact.withTemp) ? Kirigami.Theme.negativeTextColor : Kirigami.Theme.textColor
                font.family: "monospace"
                font.pointSize: compact.smallPt
                horizontalAlignment: compact.vertical ? Text.AlignHCenter : Text.AlignLeft
                verticalAlignment: Text.AlignVCenter
                Layout.preferredWidth: compact.vertical ? Math.max(1, compact.width - 2 * compact.pad) : compact.cell
                Layout.minimumWidth: Layout.preferredWidth
                Layout.maximumWidth: Layout.preferredWidth
                fontSizeMode: compact.vertical ? Text.HorizontalFit : Text.FixedSize
                minimumPointSize: 5
            }
            // down: the thin horizontal bar under the number
            Item {
                visible: compact.vertical && compact.withPct
                Layout.preferredWidth: Math.max(1, compact.width - 2 * compact.pad)
                Layout.preferredHeight: compact.barThickness
                Rectangle { anchors.fill: parent; radius: height / 2; color: Kirigami.Theme.textColor; opacity: 0.25 }
                Rectangle {
                    anchors.left: parent.left
                    height: parent.height
                    radius: height / 2
                    width: Math.max(height, parent.width * Math.max(0, Math.min(1, meter.value / 100)))
                    color: meter.fill
                }
            }
        }

        GridLayout {
            id: strip
            anchors.centerIn: parent
            columns: compact.vertical ? 1 : 4
            columnSpacing: compact.gap * 2
            rowSpacing: compact.gap * 2

            Text {
                id: gameLabel
                visible: root.showGame && root.game !== null
                text: root.game ? root.game.name : ""
                color: Kirigami.Theme.textColor
                font.bold: true
                font.pointSize: compact.smallPt
                elide: Text.ElideRight
                Layout.maximumWidth: compact.vertical ? Math.max(1, compact.width - 2 * compact.pad)
                                                      : Kirigami.Units.gridUnit * 12
                opacity: root.online ? 1 : 0.5
            }
            Meter {
                icon: "cpu"; iconFallback: "computer"
                value: root.stats.cpu || 0; temp: root.stats.cpu_temp || 0; limit: root.busyPct
            }
            Meter {
                visible: root.stats.gpu !== undefined
                icon: "video-display"; iconFallback: "preferences-desktop-display"
                value: root.stats.gpu ? root.stats.gpu.util : 0
                temp: root.stats.gpu ? root.stats.gpu.temp : 0
                limit: root.gpuFullPct
            }
            Meter {
                icon: "memory"; iconFallback: "media-flash"
                value: root.stats.mem_pct || 0; limit: root.memFullPct
            }
        }
    }
}
