import ARKit
import RealityKit
import SwiftUI

struct ContentView: View {
    @StateObject private var recordingCoordinator = RecordingCoordinator()
    @StateObject private var experimentSettings = ExperimentServerSettings()
    @StateObject private var remoteControlManager = RemoteControlManager()
    @StateObject private var liveKitPreviewManager = LiveKitPreviewManager()
    @StateObject private var thermalMonitor = ThermalMonitor()
    @State private var shareItems: [Any] = []
    @State private var isShowingShareSheet = false
    @State private var showStorageSheet = false
    @State private var showExportSheet = false
    @State private var showUploadSheet = false
    @State private var exportFolderURL: URL?
    @State private var recordingStartDate: Date?
    @State private var showGestureGuide = false
    @State private var selectedDockItem: DockItem = .record
    private let shareExportManager = ShareExportManager()

    private enum DockItem {
        case clear
        case pause
        case record
        case benchmark
        case diagnostic
        case more
    }

    var body: some View {
        ZStack {
            ARViewContainer(
                recordingCoordinator: recordingCoordinator,
                liveKitPreviewManager: liveKitPreviewManager
            )
            .ignoresSafeArea()

            // Floating chrome over AR (does not modify ARView session)
            VStack(spacing: 0) {
                topChrome
                Spacer(minLength: 0)
                bottomChrome
            }
            .padding(.top, 8)
            .zIndex(2)

            if recordingCoordinator.isCapturePaused {
                ZStack {
                    Color.black.opacity(0.35)
                        .ignoresSafeArea()
                    
                    VStack(spacing: 16) {
                        Image(systemName: "pause.circle.fill")
                            .font(.system(size: 64))
                            .foregroundStyle(Color.accentColor)
                        
                        Text("SESSION PAUSED")
                            .font(.title2.weight(.bold))
                            .foregroundStyle(Color.white)
                            .tracking(2.0)
                        
                        Text("Tap play or raise open palm to resume recording")
                            .font(.subheadline)
                            .foregroundStyle(Color.white.opacity(0.8))
                    }
                    .padding(.horizontal, 28)
                    .padding(.vertical, 24)
                    .background {
                        RoundedRectangle(cornerRadius: 24, style: .continuous)
                            .fill(Color.black.opacity(0.78))
                    }
                    .overlay {
                        RoundedRectangle(cornerRadius: 24, style: .continuous)
                            .stroke(Color.white.opacity(0.18), lineWidth: 0.75)
                    }
                    .shadow(color: Color.black.opacity(0.18), radius: 4, y: 2)
                }
                .transition(.opacity.combined(with: .scale(scale: 0.95)))
                .allowsHitTesting(false)
                .zIndex(1)
            }
        }
        .preferredColorScheme(.dark)
        .sheet(isPresented: $showStorageSheet) {
            StorageDestinationSheet(
                destinationLabel: recordingCoordinator.destinationLabel,
                onSelectInternal: {
                    recordingCoordinator.selectInternalDestination()
                },
                onSelectExternalSSD: {
                    recordingCoordinator.requestExternalFolderPicker()
                }
            )
            .presentationDetents([.medium, .large])
            .presentationDragIndicator(.visible)
            .presentationCornerRadius(28)
        }
        .sheet(isPresented: $recordingCoordinator.showingFolderPicker) {
            DocumentFolderPicker(
                onPicked: { recordingCoordinator.handleExternalFolderPicked($0) },
                onCancelled: { recordingCoordinator.handleFolderPickerCancelled() }
            )
        }
        .sheet(isPresented: $showExportSheet, onDismiss: { exportFolderURL = nil }) {
            if let url = exportFolderURL {
                ExportSessionPreviewSheet(sessionFolderName: url.lastPathComponent) {
                    Task { await exportAndPresentShare(folder: url) }
                }
                .presentationDetents([.medium, .large])
                .presentationDragIndicator(.visible)
                .presentationCornerRadius(28)
            }
        }
        .sheet(isPresented: $showUploadSheet) {
            UploadSettingsSheet(
                settings: recordingCoordinator.uploadSettings,
                experimentSettings: experimentSettings
            )
                .presentationDetents([.medium, .large])
                .presentationDragIndicator(.visible)
                .presentationCornerRadius(28)
        }
        .sheet(isPresented: $isShowingShareSheet) {
            ActivityView(items: shareItems)
        }
        .confirmationDialog(
            "iPhone is getting hot",
            isPresented: $thermalMonitor.isPromptPresented,
            titleVisibility: .visible
        ) {
            Button("Reduce load & continue") {
                thermalMonitor.acknowledge()
                recordingCoordinator.reduceLoadForThermal()
                liveKitPreviewManager.suspendForThermal()
            }
            Button("Keep full quality") {
                thermalMonitor.acknowledge()
            }
            Button("Stop & save", role: .destructive) {
                thermalMonitor.acknowledge()
                Task { await recordingCoordinator.stopForThermal() }
            }
        } message: {
            Text("SandStories can reduce LiDAR and hand-tracking work, keep full quality, or safely finish this session.")
        }
        .onChange(of: recordingCoordinator.isCaptureRecording) { _, isOn in
            if isOn {
                recordingStartDate = Date()
                thermalMonitor.evaluateForActiveSession()
            } else {
                recordingStartDate = nil
                thermalMonitor.resetForNextSession()
            }
        }
        .onAppear {
            remoteControlManager.start(settings: experimentSettings, coordinator: recordingCoordinator)
            Task { await liveKitPreviewManager.connect(settings: experimentSettings) }
        }
        .onChange(of: experimentSettings.enabled) { _, _ in
            remoteControlManager.start(settings: experimentSettings, coordinator: recordingCoordinator)
            Task { await liveKitPreviewManager.connect(settings: experimentSettings) }
        }
        .onChange(of: experimentSettings.previewEnabled) { _, _ in
            Task { await liveKitPreviewManager.connect(settings: experimentSettings) }
        }
    }

    // MARK: - Top

    private var topChrome: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .top, spacing: 8) {
                destinationPill
                    .layoutPriority(1)
                Spacer(minLength: 8)
                sessionStatusHUD
            }
            .padding(.horizontal, 16)

            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 8) {
                    gestureGuideButton
                    meshVisualizationPill

                    if !recordingCoordinator.isCaptureRecording && !recordingCoordinator.isBenchmarkRunning && !recordingCoordinator.isDepthDiagnosticRunning {
                        depthDiagnosticModePill
                    }

                    locationOverlay
                }
                .padding(.horizontal, 16)
            }

            if showGestureGuide {
                gestureGuidePanel
                    .padding(.horizontal, 16)
                    .transition(.opacity.combined(with: .move(edge: .top)))
            }

            if let warn = recordingCoordinator.warningBanner {
                statusGlassText(warn)
                    .padding(.horizontal, 16)
                    .transition(.opacity.combined(with: .move(edge: .top)))
            }

            if let summary = recordingCoordinator.benchmarkSummary {
                statusGlassText(summary, monospaced: true)
                    .padding(.horizontal, 16)
                    .transition(.opacity.combined(with: .move(edge: .top)))
            }

            if let summary = recordingCoordinator.depthDiagnosticSummary {
                statusGlassText(summary, monospaced: true)
                    .padding(.horizontal, 16)
                    .transition(.opacity.combined(with: .move(edge: .top)))
            }

            if let uploadStatus = recordingCoordinator.uploadStatus {
                statusGlassText(uploadStatus)
                    .padding(.horizontal, 16)
                    .transition(.opacity.combined(with: .move(edge: .top)))
            }

            if experimentSettings.enabled {
                statusGlassText("\(remoteControlManager.status) | \(liveKitPreviewManager.status)")
                    .padding(.horizontal, 16)
                    .transition(.opacity.combined(with: .move(edge: .top)))
            }
        }
    }

    private var gestureGuidePanel: some View {
        VStack(alignment: .leading, spacing: 8) {
            InteractiveGestureRow(
                icon: "hand.raised.fill",
                gestureName: "Open Palm (hold 3s)",
                actionDescription: "Pause / Resume Recording",
                isEnabled: $recordingCoordinator.isPauseGestureEnabled
            )
            InteractiveGestureRow(
                icon: "hand.wave.fill",
                gestureName: "Wave Hand (3 times)",
                actionDescription: "Stop Recording Session",
                isEnabled: $recordingCoordinator.isStopGestureEnabled
            )
            InteractiveGestureRow(
                icon: "hand.point.up.left.fill",
                gestureName: "One-Finger Triple Tap",
                actionDescription: "Mark Segment",
                isEnabled: $recordingCoordinator.isMarkGestureEnabled
            )
        }
        .padding(12)
        .frame(maxWidth: 464, alignment: .leading)
        .glassPanel(cornerRadius: 22, blurStyle: .systemUltraThinMaterial, shadowRadius: 12, shadowYOffset: 5)
    }

    private var destinationPill: some View {
        Button {
            guard !recordingCoordinator.isCaptureRecording else { return }
            showStorageSheet = true
        } label: {
            HStack(spacing: 12) {
                Image(systemName: destinationSystemImage)
                    .font(.body.weight(.semibold))
                    .foregroundStyle(Color.accentColor)
                    .frame(width: 28, height: 28)
                VStack(alignment: .leading, spacing: 2) {
                    Text("Save Location")
                        .font(.caption2.weight(.semibold))
                        .foregroundStyle(Color(uiColor: .label).opacity(0.78))
                    Text(destinationShortLabel)
                        .font(.footnote.weight(.semibold))
                        .foregroundStyle(Color(uiColor: .label))
                        .lineLimit(1)
                        .minimumScaleFactor(0.82)
                        .multilineTextAlignment(.leading)
                }
                Spacer(minLength: 0)
            }
            .padding(.horizontal, 14)
            .padding(.vertical, 10)
            .frame(minHeight: 52)
            .frame(maxWidth: 220, alignment: .leading)
            .glassPanel(cornerRadius: 18, blurStyle: .systemUltraThinMaterial, shadowRadius: 12, shadowYOffset: 5)
        }
        .buttonStyle(.plain)
        .accessibilityLabel(recordingCoordinator.destinationLabel)
        .disabled(recordingCoordinator.isCaptureRecording)
        .opacity(recordingCoordinator.isCaptureRecording ? 0.82 : 1)
    }

    private var destinationSystemImage: String {
        let label = recordingCoordinator.destinationLabel
        if label.contains("SSD") || label.contains("External folder") {
            return "externaldrive"
        }
        return "internaldrive"
    }

    /// Compact label for the pill (full string remains in accessibility).
    private var destinationShortLabel: String {
        let full = recordingCoordinator.destinationLabel
        if full.hasPrefix("Saving to: ") {
            return String(full.dropFirst("Saving to: ".count))
        }
        return full
    }

    private var sessionStatusHUD: some View {
        VStack(alignment: .trailing, spacing: 4) {
            if recordingCoordinator.isCaptureRecording, let start = recordingStartDate {
                TimelineView(.periodic(from: .now, by: 1)) { timeline in
                    Text(formattedDuration(from: start, to: timeline.date))
                        .font(.caption.monospacedDigit().weight(.semibold))
                        .foregroundStyle(Color(uiColor: .label))
                }
                Text("Recording")
                    .font(.caption2.weight(.medium))
                    .foregroundStyle(Color(uiColor: .secondaryLabel))
            } else {
                Text("Ready")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(Color(uiColor: .label))
                Text("Not recording")
                    .font(.caption2)
                    .foregroundStyle(Color(uiColor: .tertiaryLabel))
            }
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 9)
        .frame(minWidth: 108)
        .glassPanel(cornerRadius: 18, blurStyle: .systemUltraThinMaterial, shadowRadius: 12, shadowYOffset: 5)
        .accessibilityElement(children: .combine)
        .accessibilityLabel(sessionAccessibilityLabel)
    }

    private var sessionAccessibilityLabel: String {
        if recordingCoordinator.isCaptureRecording, let start = recordingStartDate {
            return "Recording, elapsed \(formattedDuration(from: start, to: Date()))"
        }
        return "Ready, not recording"
    }

    private func formattedDuration(from start: Date, to end: Date) -> String {
        let s = max(0, Int(end.timeIntervalSince(start)))
        let m = s / 60
        let r = s % 60
        return String(format: "%d:%02d", m, r)
    }

    private var locationOverlay: some View {
        Label(recordingCoordinator.locationCaptureManager.coordinateDisplay, systemImage: "location.fill")
            .font(.caption.monospacedDigit())
            .labelStyle(.titleAndIcon)
            .foregroundStyle(Color(uiColor: .secondaryLabel))
            .lineLimit(1)
            .minimumScaleFactor(0.72)
            .padding(.horizontal, 14)
            .padding(.vertical, 10)
            .frame(minHeight: 44)
            .glassPanel(cornerRadius: 15, blurStyle: .systemUltraThinMaterial, shadowRadius: 8, shadowYOffset: 3)
            .allowsHitTesting(false)
    }

    private var meshVisualizationPill: some View {
        let isSupported = ARWorldTrackingConfiguration.supportsSceneReconstruction(.mesh)
        let isAvailable = isSupported &&
            !recordingCoordinator.isCaptureRecording &&
            recordingCoordinator.capturePerformanceMode == .fullQuality
        return Button {
            guard isAvailable else { return }
            withAnimation(.spring(duration: 0.25, bounce: 0.16)) {
                recordingCoordinator.isMeshVisualizationEnabled.toggle()
            }
        } label: {
            HStack(spacing: 8) {
                Image(systemName: recordingCoordinator.isMeshVisualizationEnabled ? "cube.fill" : "cube")
                    .font(.body.weight(.semibold))
                Text(recordingCoordinator.isMeshVisualizationEnabled ? "Hide Mesh" : "Show Mesh")
                    .font(.subheadline.weight(.semibold))
                    .lineLimit(1)
                    .minimumScaleFactor(0.85)
            }
            .foregroundStyle(recordingCoordinator.isMeshVisualizationEnabled ? Color.accentColor : Color(uiColor: .secondaryLabel))
            .padding(.horizontal, 14)
            .padding(.vertical, 10)
            .frame(minHeight: 44)
            .glassPanel(cornerRadius: 16, blurStyle: .systemThinMaterial, shadowRadius: 8, shadowYOffset: 3)
        }
        .buttonStyle(.plain)
        .disabled(!isAvailable)
        .opacity(isAvailable ? 1 : 0.42)
        .accessibilityLabel(recordingCoordinator.isMeshVisualizationEnabled ? "Turn mesh visualization off" : "Turn mesh visualization on")
        .accessibilityHint("Shows or hides the LiDAR scene mesh overlay.")
    }

    private var depthDiagnosticModePill: some View {
        Button {
            withAnimation(.spring(duration: 0.3, bounce: 0.18)) {
                recordingCoordinator.isDepthDiagnosticRawOnly.toggle()
            }
        } label: {
            HStack(spacing: 8) {
                Image(systemName: recordingCoordinator.isDepthDiagnosticRawOnly ? "waveform.path.ecg" : "waveform.path")
                    .font(.body.weight(.semibold))
                Text(recordingCoordinator.isDepthDiagnosticRawOnly ? "Raw Depth Only" : "Raw + Smoothed")
                    .font(.subheadline.weight(.semibold))
                    .lineLimit(1)
                    .minimumScaleFactor(0.85)
            }
            .foregroundStyle(Color.accentColor)
            .padding(.horizontal, 14)
            .padding(.vertical, 10)
            .frame(minHeight: 44)
            .glassPanel(cornerRadius: 16, blurStyle: .systemThinMaterial, shadowRadius: 8, shadowYOffset: 3)
        }
        .buttonStyle(.plain)
        .accessibilityLabel(recordingCoordinator.isDepthDiagnosticRawOnly ? "Depth diagnostic raw only" : "Depth diagnostic raw and smoothed")
    }

    private func statusGlassText(_ text: String, monospaced: Bool = false) -> some View {
        Text(text)
            .font(monospaced ? .caption.monospacedDigit() : .caption)
            .foregroundStyle(Color(uiColor: .secondaryLabel))
            .lineLimit(2)
            .minimumScaleFactor(0.82)
            .multilineTextAlignment(.leading)
            .padding(.horizontal, 12)
            .padding(.vertical, 8)
            .frame(maxWidth: .infinity, alignment: .leading)
            .glassPanel(cornerRadius: 15, blurStyle: .systemUltraThinMaterial, shadowRadius: 8, shadowYOffset: 3)
    }

    // MARK: - Bottom

    private var bottomChrome: some View {
        VStack(spacing: 8) {
            CameraZoomRail(
                zoomController: recordingCoordinator.zoomController,
                isRecording: recordingCoordinator.isCaptureRecording
            )

            HStack(spacing: 8) {
                clearToolbarButton
                pauseFloatingButton
                recordFloatingButton
                benchmarkToolbarButton
                diagnosticToolbarButton
                moreToolbarButton
            }
            .padding(.horizontal, 9)
            .padding(.vertical, 8)
            .frame(maxWidth: 430)
            .liquidGlassDock()
        }
        .padding(.horizontal, 16)
        .padding(.bottom, 10)
        .safeAreaPadding(.bottom, 8)
        .accessibilityElement(children: .contain)
    }

    private var pauseFloatingButton: some View {
        let isDisabled = !recordingCoordinator.isCaptureRecording
        return liquidDockButton(
            item: .pause,
            title: recordingCoordinator.isCapturePaused ? "Resume" : "Pause",
            systemImage: recordingCoordinator.isCapturePaused ? "play.fill" : "pause.fill",
            accessibilityLabel: recordingCoordinator.isCapturePaused ? "Resume session recording" : "Pause session recording",
            foregroundStyle: recordingCoordinator.isCapturePaused ? Color.accentColor : Color(uiColor: .label),
            isDisabled: isDisabled,
            isHighlighted: recordingCoordinator.isCapturePaused
        ) {
            Task {
                await recordingCoordinator.togglePauseCaptureSession()
            }
        }
    }

    private var recordFloatingButton: some View {
        let isDisabled = !recordingCoordinator.isCaptureRecording && (recordingCoordinator.isBenchmarkRunning || recordingCoordinator.isDepthDiagnosticRunning)
        return liquidDockButton(
            item: .record,
            title: recordingCoordinator.isCaptureRecording ? "Stop" : "Record",
            systemImage: recordingCoordinator.isCaptureRecording ? "stop.fill" : "record.circle.fill",
            accessibilityLabel: recordingCoordinator.isCaptureRecording ? "Stop session recording" : "Start session recording",
            foregroundStyle: recordingCoordinator.isCaptureRecording ? Color(uiColor: .systemRed) : Color.accentColor,
            isDisabled: isDisabled,
            isHighlighted: recordingCoordinator.isCaptureRecording,
            expandedWidth: 92
        ) {
            Task {
                await recordingCoordinator.toggleRecording()
            }
        }
    }

    private var clearToolbarButton: some View {
        liquidDockButton(
            item: .clear,
            title: "Clear",
            systemImage: "paintbrush.pointed",
            accessibilityLabel: "Clear strokes",
            foregroundStyle: Color(uiColor: .label),
            isDisabled: false,
            isHighlighted: false
        ) {
            Task {
                await recordingCoordinator.handPoseManager.clearStrokes()
            }
        }
    }

    private var benchmarkToolbarButton: some View {
        liquidDockButton(
            item: .benchmark,
            title: "Bench",
            systemImage: "speedometer",
            accessibilityLabel: "Run 15 second depth capture benchmark",
            foregroundStyle: recordingCoordinator.isBenchmarkRunning ? Color(uiColor: .secondaryLabel) : Color.accentColor,
            isDisabled: recordingCoordinator.isCaptureRecording || recordingCoordinator.isBenchmarkRunning || recordingCoordinator.isDepthDiagnosticRunning,
            isHighlighted: recordingCoordinator.isBenchmarkRunning
        ) {
            Task {
                await recordingCoordinator.runDepthBenchmark()
            }
        }
    }

    private var diagnosticToolbarButton: some View {
        liquidDockButton(
            item: .diagnostic,
            title: "Depth",
            systemImage: recordingCoordinator.isDepthDiagnosticRawOnly ? "waveform.path.ecg" : "waveform.path",
            accessibilityLabel: "Run 20 second depth diagnostic capture",
            foregroundStyle: recordingCoordinator.isDepthDiagnosticRunning ? Color(uiColor: .secondaryLabel) : Color.accentColor,
            isDisabled: recordingCoordinator.isCaptureRecording || recordingCoordinator.isBenchmarkRunning || recordingCoordinator.isDepthDiagnosticRunning,
            isHighlighted: recordingCoordinator.isDepthDiagnosticRunning || recordingCoordinator.isDepthDiagnosticRawOnly
        ) {
            Task {
                await recordingCoordinator.runDepthDiagnostic()
            }
        }
        .contextMenu {
            Toggle("Raw only", isOn: $recordingCoordinator.isDepthDiagnosticRawOnly)
        }
    }

    private var moreToolbarButton: some View {
        Menu {
            Button {
                withAnimation(.spring(response: 0.34, dampingFraction: 0.78)) {
                    selectedDockItem = .more
                }
                showUploadSheet = true
            } label: {
                Label("Upload Settings", systemImage: recordingCoordinator.uploadSettings.enabled ? "icloud.and.arrow.up.fill" : "icloud.and.arrow.up")
            }
            .disabled(recordingCoordinator.isCaptureRecording)

            Button {
                withAnimation(.spring(response: 0.34, dampingFraction: 0.78)) {
                    selectedDockItem = .more
                }
                Task {
                    guard let folder = recordingCoordinator.lastSessionFolderURL else {
                        print("Share: no session folder yet - record a session first.")
                        return
                    }
                    await MainActor.run {
                        exportFolderURL = folder
                        showExportSheet = true
                    }
                }
            } label: {
                Label("Export Last Session", systemImage: "square.and.arrow.up")
            }
        } label: {
            dockControl(
                item: .more,
                title: "More",
                systemImage: "ellipsis",
                foregroundStyle: recordingCoordinator.uploadSettings.enabled ? Color.accentColor : Color(uiColor: .label),
                isHighlighted: recordingCoordinator.uploadSettings.enabled
            )
        }
        .simultaneousGesture(
            TapGesture().onEnded {
                withAnimation(.spring(response: 0.34, dampingFraction: 0.78)) {
                    selectedDockItem = .more
                }
            }
        )
        .buttonStyle(LiquidButtonStyle())
        .accessibilityLabel("More capture actions")
    }

    private func liquidDockButton(
        item: DockItem,
        title: String,
        systemImage: String,
        accessibilityLabel: String,
        foregroundStyle: Color,
        isDisabled: Bool,
        isHighlighted: Bool,
        expandedWidth: CGFloat = 88,
        action: @escaping () -> Void
    ) -> some View {
        Button {
            withAnimation(.spring(response: 0.34, dampingFraction: 0.78)) {
                selectedDockItem = item
            }
            action()
        } label: {
            dockControl(
                item: item,
                title: title,
                systemImage: systemImage,
                foregroundStyle: foregroundStyle,
                isHighlighted: isHighlighted,
                expandedWidth: expandedWidth
            )
        }
        .buttonStyle(LiquidButtonStyle())
        .disabled(isDisabled)
        .opacity(isDisabled ? 0.42 : 1)
        .accessibilityLabel(accessibilityLabel)
    }

    private func dockControl(
        item: DockItem,
        title: String,
        systemImage: String,
        foregroundStyle: Color,
        isHighlighted: Bool,
        expandedWidth: CGFloat = 88
    ) -> some View {
        let isSelected = selectedDockItem == item
        let tint = isHighlighted || isSelected

        return HStack(spacing: isSelected ? 7 : 0) {
            Image(systemName: systemImage)
                .font(.body.weight(.semibold))
                .symbolRenderingMode(.hierarchical)
                .foregroundStyle(foregroundStyle)
                .frame(width: 22, height: 22)

            if isSelected {
                Text(title)
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(foregroundStyle)
                    .lineLimit(1)
                    .minimumScaleFactor(0.82)
                    .transition(.opacity.combined(with: .move(edge: .trailing)))
            }
        }
        .frame(width: isSelected ? expandedWidth : 42, height: 46)
        .background {
            if isSelected {
                Capsule(style: .continuous)
                    .fill(Color.white.opacity(isHighlighted ? 0.18 : 0.10))
                    .overlay {
                        Capsule(style: .continuous)
                            .stroke(Color.white.opacity(0.16), lineWidth: 0.75)
                    }
            }
        }
        .opacity(tint ? 1 : 0.74)
        .contentShape(Capsule(style: .continuous))
        .animation(.easeOut(duration: 0.18), value: isSelected)
    }

    // MARK: - Export (same zip + activity flow as before)

    private func exportAndPresentShare(folder: URL) async {
        do {
            let zipURL = try await shareExportManager.zipSessionFolder(folder)
            await MainActor.run {
                shareItems = [zipURL]
                showExportSheet = false
                exportFolderURL = nil
            }
            try await Task.sleep(nanoseconds: 350_000_000)
            await MainActor.run {
                isShowingShareSheet = true
            }
        } catch {
            print("Share export error: \(error)")
        }
    }
}

// MARK: - AR container

struct ARViewContainer: UIViewRepresentable {
    @ObservedObject var recordingCoordinator: RecordingCoordinator
    @ObservedObject var liveKitPreviewManager: LiveKitPreviewManager

    @MainActor
    final class Coordinator {
        let multiplexer: ARSessionDelegateMultiplexer
        let previewForwarder: ARFramePreviewForwarder
        var meshVisualizationEnabled: Bool?
        var performanceMode: CapturePerformanceMode?
        var isCaptureRecording: Bool?

        init(
            depth: DepthCaptureManager,
            hand: HandPoseCaptureManager,
            pipeline: SessionFramePipeline,
            previewManager: LiveKitPreviewManager
        ) {
            previewForwarder = ARFramePreviewForwarder(previewManager: previewManager)
            multiplexer = ARSessionDelegateMultiplexer([depth, hand, pipeline, previewForwarder])
        }
    }

    @MainActor
    func makeCoordinator() -> Coordinator {
        Coordinator(
            depth: recordingCoordinator.depthCaptureManager,
            hand: recordingCoordinator.handPoseManager,
            pipeline: recordingCoordinator.framePipeline,
            previewManager: liveKitPreviewManager
        )
    }

    @MainActor
    func makeUIView(context: Context) -> ARView {
        let arView = ARView(frame: .zero, cameraMode: .ar, automaticallyConfigureSession: false)

        arView.renderOptions.insert(.disableCameraGrain)
        arView.renderOptions.insert(.disableMotionBlur)
        arView.renderOptions.insert(.disableDepthOfField)
        arView.renderOptions.insert(.disableGroundingShadows)
        arView.renderOptions.insert(.disableAREnvironmentLighting)
        arView.renderOptions.insert(.disablePersonOcclusion)

        arView.session.delegate = context.coordinator.multiplexer
        recordingCoordinator.handPoseManager.setARView(arView)

        configureAndRunSession(
            for: arView,
            meshVisualizationEnabled: recordingCoordinator.isMeshVisualizationEnabled,
            performanceMode: recordingCoordinator.capturePerformanceMode,
            isCaptureRecording: recordingCoordinator.isCaptureRecording,
            options: [.resetTracking, .removeExistingAnchors]
        )
        context.coordinator.meshVisualizationEnabled = recordingCoordinator.isMeshVisualizationEnabled
        context.coordinator.performanceMode = recordingCoordinator.capturePerformanceMode
        context.coordinator.isCaptureRecording = recordingCoordinator.isCaptureRecording
        recordingCoordinator.depthCaptureManager.setRecording(recordingCoordinator.isCaptureRecording)
        return arView
    }

    @MainActor
    func updateUIView(_ uiView: ARView, context: Context) {
        recordingCoordinator.depthCaptureManager.setRecording(recordingCoordinator.isCaptureRecording)

        let needsReconfiguration =
            context.coordinator.meshVisualizationEnabled != recordingCoordinator.isMeshVisualizationEnabled ||
            context.coordinator.performanceMode != recordingCoordinator.capturePerformanceMode ||
            context.coordinator.isCaptureRecording != recordingCoordinator.isCaptureRecording

        if needsReconfiguration {
            configureAndRunSession(
                for: uiView,
                meshVisualizationEnabled: recordingCoordinator.isMeshVisualizationEnabled,
                performanceMode: recordingCoordinator.capturePerformanceMode,
                isCaptureRecording: recordingCoordinator.isCaptureRecording,
                options: []
            )
            context.coordinator.meshVisualizationEnabled = recordingCoordinator.isMeshVisualizationEnabled
            context.coordinator.performanceMode = recordingCoordinator.capturePerformanceMode
            context.coordinator.isCaptureRecording = recordingCoordinator.isCaptureRecording
        }
    }

    @MainActor
    static func dismantleUIView(_ uiView: ARView, coordinator: Coordinator) {
        uiView.session.pause()
    }

    @MainActor
    private func configureAndRunSession(
        for arView: ARView,
        meshVisualizationEnabled: Bool,
        performanceMode: CapturePerformanceMode,
        isCaptureRecording: Bool,
        options: ARSession.RunOptions
    ) {
        guard ARWorldTrackingConfiguration.isSupported else { return }

        let configuration = ARWorldTrackingConfiguration()
        configuration.videoHDRAllowed = false

        let thirtyFPSFormats = ARWorldTrackingConfiguration.supportedVideoFormats.filter {
            $0.framesPerSecond == 30
        }
        if let videoFormat = thirtyFPSFormats.first(where: {
            max($0.imageResolution.width, $0.imageResolution.height) <= 1_920
        }) ?? thirtyFPSFormats.last {
            configuration.videoFormat = videoFormat
        }

        let supportsSceneDepth = ARWorldTrackingConfiguration.supportsFrameSemantics(.sceneDepth)
        let supportsSmoothedSceneDepth = ARWorldTrackingConfiguration.supportsFrameSemantics(.smoothedSceneDepth)

        if supportsSceneDepth {
            configuration.frameSemantics.insert(.sceneDepth)
        }
        if performanceMode == .fullQuality, supportsSmoothedSceneDepth {
            configuration.frameSemantics.insert(.smoothedSceneDepth)
        }
        if !supportsSceneDepth, supportsSmoothedSceneDepth {
            configuration.frameSemantics.insert(.smoothedSceneDepth)
        }

        if !supportsSceneDepth && !supportsSmoothedSceneDepth {
            recordingCoordinator.warningBanner = "LiDAR depth unavailable on this device; use a LiDAR-capable iPhone or iPad for depth capture."
        }

        let canShowMesh =
            meshVisualizationEnabled &&
            !isCaptureRecording &&
            performanceMode == .fullQuality &&
            ARWorldTrackingConfiguration.supportsSceneReconstruction(.mesh)

        if canShowMesh {
            configuration.sceneReconstruction = .mesh
            arView.debugOptions.insert(.showSceneUnderstanding)
        } else {
            arView.debugOptions.remove(.showSceneUnderstanding)
        }

        // Configure the underlying capture device before ARKit starts, then
        // reapply after startup because ARKit may restore camera defaults.
        recordingCoordinator.zoomController.prepareForARSession()
        arView.session.run(configuration, options: options)
        recordingCoordinator.zoomController.reapplyAfterARSessionStart()
    }
}
// MARK: - Gesture UI Helpers

extension ContentView {
    private var gestureGuideButton: some View {
        Button {
            withAnimation(.spring(duration: 0.35, bounce: 0.2)) {
                showGestureGuide.toggle()
            }
        } label: {
            HStack(spacing: 8) {
                Image(systemName: "hand.raised.fill")
                    .font(.body.weight(.semibold))
                Text(showGestureGuide ? "Hide Gestures" : "Gestures")
                    .font(.subheadline.weight(.semibold))
                    .lineLimit(1)
                    .minimumScaleFactor(0.85)
            }
            .foregroundStyle(showGestureGuide ? Color.accentColor : Color(uiColor: .label))
            .padding(.horizontal, 14)
            .padding(.vertical, 10)
            .frame(minHeight: 44)
            .glassPanel(cornerRadius: 16, blurStyle: .systemThinMaterial, shadowRadius: 8, shadowYOffset: 3)
        }
        .buttonStyle(.plain)
        .accessibilityLabel("Show gestures guide")
    }
}

struct InteractiveGestureRow: View {
    let icon: String
    let gestureName: String
    let actionDescription: String
    @Binding var isEnabled: Bool
    
    var body: some View {
        Button {
            withAnimation(.spring(duration: 0.2, bounce: 0.1)) {
                isEnabled.toggle()
            }
        } label: {
            HStack(spacing: 12) {
                Image(systemName: icon)
                    .font(.title3)
                    .foregroundStyle(isEnabled ? Color.accentColor : Color(uiColor: .tertiaryLabel))
                    .frame(width: 28, height: 28)
                    .background {
                        Circle()
                            .fill(isEnabled ? Color.accentColor.opacity(0.10) : Color(uiColor: .systemFill).opacity(0.18))
                    }
                
                VStack(alignment: .leading, spacing: 2) {
                    Text(gestureName)
                        .font(.footnote.weight(.semibold))
                        .foregroundStyle(isEnabled ? Color(uiColor: .label) : Color(uiColor: .secondaryLabel))
                    Text(actionDescription)
                        .font(.caption2)
                        .foregroundStyle(Color(uiColor: .secondaryLabel))
                }
                
                Spacer()
                
                Image(systemName: isEnabled ? "checkmark.circle.fill" : "circle")
                    .font(.title3)
                    .foregroundStyle(isEnabled ? Color.accentColor : Color(uiColor: .tertiaryLabel))
            }
            .padding(.vertical, 10)
            .padding(.horizontal, 12)
            .background {
                RoundedRectangle(cornerRadius: 14)
                    .fill(isEnabled ? Color.accentColor.opacity(0.03) : Color.clear)
            }
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }
}

struct LiquidButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .scaleEffect(configuration.isPressed ? 0.90 : 1.0)
            .opacity(configuration.isPressed ? 0.8 : 1.0)
            .animation(.spring(response: 0.3, dampingFraction: 0.6), value: configuration.isPressed)
    }
}
