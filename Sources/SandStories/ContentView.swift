import ARKit
import RealityKit
import SwiftUI

struct ContentView: View {
    @StateObject private var recordingCoordinator = RecordingCoordinator()
    @StateObject private var experimentSettings = ExperimentServerSettings()
    @StateObject private var remoteControlManager = RemoteControlManager()
    @StateObject private var liveKitPreviewManager = LiveKitPreviewManager()
    @State private var shareItems: [Any] = []
    @State private var isShowingShareSheet = false
    @State private var showStorageSheet = false
    @State private var showExportSheet = false
    @State private var showUploadSheet = false
    @State private var exportFolderURL: URL?
    @State private var recordingStartDate: Date?
    @State private var showGestureGuide = false
    private let shareExportManager = ShareExportManager()

    var body: some View {
        ZStack {
            ARViewContainer(
                recordingCoordinator: recordingCoordinator
            )
            .ignoresSafeArea()

            // Floating chrome over AR (does not modify ARView session)
            VStack(spacing: 0) {
                topChrome
                Spacer(minLength: 0)
                bottomChrome
            }
            .padding(.top, 8)

            if showGestureGuide {
                VStack(alignment: .leading, spacing: 14) {
                    HStack {
                        Text("Gestures")
                            .font(.headline.weight(.bold))
                        Spacer()
                        Button {
                            withAnimation(.spring(duration: 0.3, bounce: 0.15)) { showGestureGuide = false }
                        } label: {
                            Image(systemName: "xmark.circle.fill")
                                .font(.title2)
                                .foregroundStyle(Color(uiColor: .secondaryLabel))
                        }
                        .buttonStyle(.plain)
                    }
                    
                    Divider()
                    
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
                }
                .padding(16)
                .background {
                    VisualEffectBlur(style: .systemMaterial)
                        .clipShape(RoundedRectangle(cornerRadius: 20))
                }
                .overlay {
                    RoundedRectangle(cornerRadius: 20)
                        .stroke(Color(uiColor: .label).opacity(0.15), lineWidth: 1)
                }
                .shadow(color: Color.black.opacity(0.15), radius: 15, y: 5)
                .frame(maxWidth: 310)
                .padding(.horizontal, 16)
                .padding(.top, 80) // Below top HUD
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topTrailing)
                .transition(.opacity.combined(with: .move(edge: .top)))
            }

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
                        
                        Text("Raise open palm to resume recording")
                            .font(.subheadline)
                            .foregroundStyle(Color.white.opacity(0.8))
                    }
                    .padding(.horizontal, 28)
                    .padding(.vertical, 24)
                    .background {
                        VisualEffectBlur(style: .systemUltraThinMaterial)
                            .clipShape(RoundedRectangle(cornerRadius: 24))
                    }
                    .overlay {
                        RoundedRectangle(cornerRadius: 24)
                            .stroke(Color.white.opacity(0.25), lineWidth: 1)
                    }
                    .shadow(color: Color.black.opacity(0.3), radius: 25, y: 10)
                }
                .transition(.opacity.combined(with: .scale(scale: 0.95)))
            }
        }
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
        .onChange(of: recordingCoordinator.isCaptureRecording) { _, isOn in
            if isOn {
                recordingStartDate = Date()
            } else {
                recordingStartDate = nil
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
        .animation(.spring(duration: 0.35, bounce: 0.22), value: recordingCoordinator.isCaptureRecording)
    }

    // MARK: - Top

    private var topChrome: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .top, spacing: 8) {
                destinationPill
                Spacer(minLength: 4)
                gestureGuideButton
                sessionStatusHUD
            }
            .padding(.horizontal, 16)

            HStack(spacing: 8) {
                locationOverlay
                    .layoutPriority(1)

                if !recordingCoordinator.isCaptureRecording && !recordingCoordinator.isBenchmarkRunning && !recordingCoordinator.isDepthDiagnosticRunning {
                    depthDiagnosticModePill
                }
            }
            .padding(.horizontal, 16)

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

    private var destinationPill: some View {
        Button {
            guard !recordingCoordinator.isCaptureRecording else { return }
            showStorageSheet = true
        } label: {
            HStack(spacing: 10) {
                Image(systemName: destinationSystemImage)
                    .font(.body.weight(.semibold))
                    .foregroundStyle(Color.accentColor)
                    .frame(width: 28, height: 28)
                Text(destinationShortLabel)
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(Color(uiColor: .label))
                    .lineLimit(1)
                    .minimumScaleFactor(0.82)
                    .multilineTextAlignment(.leading)
                Spacer(minLength: 0)
            }
            .padding(.leading, 12)
            .padding(.trailing, 14)
            .padding(.vertical, 9)
            .frame(minHeight: 42)
            .frame(maxWidth: 220, alignment: .leading)
            .glassPanel(cornerRadius: 21, blurStyle: .systemUltraThinMaterial, shadowRadius: 12, shadowYOffset: 5)
        }
        .buttonStyle(.plain)
        .accessibilityLabel(recordingCoordinator.destinationLabel)
        .disabled(recordingCoordinator.isCaptureRecording)
        .opacity(recordingCoordinator.isCaptureRecording ? 0.5 : 1)
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
                TimelineView(.periodic(from: .now, by: 0.2)) { timeline in
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
            .padding(.horizontal, 11)
            .padding(.vertical, 7)
            .frame(maxWidth: .infinity, alignment: .leading)
            .glassPanel(cornerRadius: 15, blurStyle: .systemUltraThinMaterial, shadowRadius: 8, shadowYOffset: 3)
            .allowsHitTesting(false)
    }

    private var depthDiagnosticModePill: some View {
        Button {
            withAnimation(.spring(duration: 0.3, bounce: 0.18)) {
                recordingCoordinator.isDepthDiagnosticRawOnly.toggle()
            }
        } label: {
            HStack(spacing: 6) {
                Image(systemName: recordingCoordinator.isDepthDiagnosticRawOnly ? "waveform.path.ecg" : "waveform.path")
                    .font(.caption.weight(.bold))
                Text(recordingCoordinator.isDepthDiagnosticRawOnly ? "Raw" : "Raw+S")
                    .font(.caption.weight(.bold))
                    .lineLimit(1)
            }
            .foregroundStyle(Color.accentColor)
            .padding(.horizontal, 11)
            .padding(.vertical, 7)
            .glassPanel(cornerRadius: 15, blurStyle: .systemUltraThinMaterial, shadowRadius: 8, shadowYOffset: 3)
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
        VStack(spacing: 18) {
            recordFloatingButton

            HStack(spacing: 12) {
                clearToolbarButton
                benchmarkToolbarButton
                diagnosticToolbarButton
                uploadToolbarButton
                shareToolbarButton
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 10)
            .frame(maxWidth: 360)
            .glassPanel(cornerRadius: 30, blurStyle: .systemUltraThinMaterial, shadowRadius: 22, shadowYOffset: 10)
            .padding(.horizontal, 20)
        }
        .padding(.bottom, 12)
        .safeAreaPadding(.bottom, 8)
    }

    private var recordFloatingButton: some View {
        Button {
            Task {
                await recordingCoordinator.toggleRecording()
            }
        } label: {
            ZStack {
                Circle()
                    .fill(Color.clear)
                    .frame(width: 76, height: 76)
                    .background {
                        VisualEffectBlur(
                            style: recordingCoordinator.isCaptureRecording
                                ? .systemThinMaterial
                                : .systemUltraThinMaterial
                        )
                        .clipShape(Circle())
                    }
                    .overlay {
                        Circle()
                            .stroke(
                                LinearGradient(
                                    colors: [
                                        Color.white.opacity(0.36),
                                        Color.white.opacity(0.08),
                                        Color.black.opacity(0.18)
                                    ],
                                    startPoint: .topLeading,
                                    endPoint: .bottomTrailing
                                ),
                                lineWidth: 1
                            )
                    }
                    .shadow(color: Color.black.opacity(0.32), radius: 22, y: 10)

                if recordingCoordinator.isCaptureRecording {
                    Image(systemName: "stop.circle.fill")
                        .font(.system(size: 40))
                        .symbolRenderingMode(.palette)
                        .foregroundStyle(Color(uiColor: .systemRed), Color(uiColor: .tertiaryLabel))
                } else {
                    Image(systemName: "record.circle")
                        .font(.system(size: 40))
                        .symbolRenderingMode(.hierarchical)
                        .foregroundStyle(Color.accentColor)
                }
            }
            .frame(width: 76, height: 76)
        }
        .buttonStyle(.plain)
        .frame(minWidth: 44, minHeight: 44)
        .accessibilityLabel(recordingCoordinator.isCaptureRecording ? "Stop session recording" : "Start session recording")
        .disabled(recordingCoordinator.isBenchmarkRunning || recordingCoordinator.isDepthDiagnosticRunning)
        .opacity((recordingCoordinator.isBenchmarkRunning || recordingCoordinator.isDepthDiagnosticRunning) ? 0.5 : 1)
    }

    private var clearToolbarButton: some View {
        toolDockButton(
            systemImage: "paintbrush.pointed",
            accessibilityLabel: "Clear strokes",
            foregroundStyle: Color(uiColor: .label),
            isDisabled: false
        ) {
            Task {
                await recordingCoordinator.handPoseManager.clearStrokes()
            }
        }
    }

    private var benchmarkToolbarButton: some View {
        toolDockButton(
            systemImage: "speedometer",
            accessibilityLabel: "Run 15 second depth capture benchmark",
            foregroundStyle: recordingCoordinator.isBenchmarkRunning ? Color(uiColor: .secondaryLabel) : Color.accentColor,
            isDisabled: recordingCoordinator.isCaptureRecording || recordingCoordinator.isBenchmarkRunning || recordingCoordinator.isDepthDiagnosticRunning
        ) {
            Task {
                await recordingCoordinator.runDepthBenchmark()
            }
        }
    }

    private var diagnosticToolbarButton: some View {
        toolDockButton(
            systemImage: recordingCoordinator.isDepthDiagnosticRawOnly ? "waveform.path.ecg" : "waveform.path",
            accessibilityLabel: "Run 20 second depth diagnostic capture",
            foregroundStyle: recordingCoordinator.isDepthDiagnosticRunning ? Color(uiColor: .secondaryLabel) : Color.accentColor,
            isDisabled: recordingCoordinator.isCaptureRecording || recordingCoordinator.isBenchmarkRunning || recordingCoordinator.isDepthDiagnosticRunning
        ) {
            Task {
                await recordingCoordinator.runDepthDiagnostic()
            }
        }
        .contextMenu {
            Toggle("Raw only", isOn: $recordingCoordinator.isDepthDiagnosticRawOnly)
        }
    }

    private var shareToolbarButton: some View {
        toolDockButton(
            systemImage: "square.and.arrow.up",
            accessibilityLabel: "Share last session",
            foregroundStyle: Color.accentColor,
            isDisabled: false
        ) {
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
        }
    }

    private var uploadToolbarButton: some View {
        toolDockButton(
            systemImage: recordingCoordinator.uploadSettings.enabled ? "icloud.and.arrow.up.fill" : "icloud.and.arrow.up",
            accessibilityLabel: "Configure automatic upload",
            foregroundStyle: recordingCoordinator.uploadSettings.enabled ? Color.accentColor : Color(uiColor: .label),
            isDisabled: recordingCoordinator.isCaptureRecording
        ) {
            showUploadSheet = true
        }
    }

    private func toolDockButton(
        systemImage: String,
        accessibilityLabel: String,
        foregroundStyle: Color,
        isDisabled: Bool,
        action: @escaping () -> Void
    ) -> some View {
        Button(action: action) {
            Image(systemName: systemImage)
                .font(.system(size: 21, weight: .semibold))
                .symbolRenderingMode(.hierarchical)
                .foregroundStyle(foregroundStyle)
                .frame(width: 46, height: 46)
                .background {
                    Circle()
                        .fill(Color(uiColor: .secondarySystemFill).opacity(0.28))
                }
                .contentShape(Circle())
        }
        .buttonStyle(LiquidButtonStyle())
        .disabled(isDisabled)
        .opacity(isDisabled ? 0.42 : 1)
        .accessibilityLabel(accessibilityLabel)
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

// MARK: - AR container (unchanged capture configuration)

struct ARViewContainer: UIViewRepresentable {
    @ObservedObject var recordingCoordinator: RecordingCoordinator

    @MainActor
    final class Coordinator {
        let multiplexer: ARSessionDelegateMultiplexer

        init(
            depth: DepthCaptureManager,
            hand: HandPoseCaptureManager,
            pipeline: SessionFramePipeline
        ) {
            multiplexer = ARSessionDelegateMultiplexer([depth, hand, pipeline])
        }
    }

    @MainActor
    func makeCoordinator() -> Coordinator {
        Coordinator(
            depth: recordingCoordinator.depthCaptureManager,
            hand: recordingCoordinator.handPoseManager,
            pipeline: recordingCoordinator.framePipeline
        )
    }

    @MainActor
    func makeUIView(context: Context) -> ARView {
        let arView = ARView(frame: .zero, cameraMode: .ar, automaticallyConfigureSession: false)

        // LiDAR scene mesh overlay: colored triangle mesh that visualizes scanned geometry.
        arView.debugOptions.insert(.showSceneUnderstanding)

        arView.session.delegate = context.coordinator.multiplexer
        recordingCoordinator.handPoseManager.setARView(arView)

        configureAndRunSession(for: arView)
        recordingCoordinator.depthCaptureManager.setRecording(recordingCoordinator.isCaptureRecording)

        Task { await recordingCoordinator.locationCaptureManager.startCapture() }
        return arView
    }

    @MainActor
    func updateUIView(_ uiView: ARView, context: Context) {
        recordingCoordinator.depthCaptureManager.setRecording(recordingCoordinator.isCaptureRecording)
    }

    @MainActor
    static func dismantleUIView(_ uiView: ARView, coordinator: Coordinator) {
        uiView.session.pause()
    }

    @MainActor
    private func configureAndRunSession(for arView: ARView) {
        guard ARWorldTrackingConfiguration.isSupported else { return }

        let configuration = ARWorldTrackingConfiguration()

        if ARWorldTrackingConfiguration.supportsFrameSemantics(.sceneDepth) {
            configuration.frameSemantics.insert(.sceneDepth)
        }

        if ARWorldTrackingConfiguration.supportsFrameSemantics(.smoothedSceneDepth) {
            configuration.frameSemantics.insert(.smoothedSceneDepth)
        }

        // Build the LiDAR scene mesh so the colored mesh overlay has geometry to draw.
        if ARWorldTrackingConfiguration.supportsSceneReconstruction(.mesh) {
            configuration.sceneReconstruction = .mesh
        }

        arView.session.run(configuration, options: [.resetTracking, .removeExistingAnchors])
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
            Image(systemName: "hand.raised.fill")
                .font(.body.weight(.semibold))
                .foregroundStyle(showGestureGuide ? Color.white : Color.accentColor)
                .frame(width: 44, height: 44)
                .background {
                    VisualEffectBlur(style: showGestureGuide ? .systemMaterial : .systemThinMaterial)
                        .clipShape(Circle())
                }
                .overlay {
                    Circle()
                        .stroke(Color(uiColor: .label).opacity(0.15), lineWidth: 1)
                }
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
                            .fill(isEnabled ? Color.accentColor.opacity(0.15) : Color(uiColor: .quaternarySystemFill))
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
                    .fill(isEnabled ? Color.accentColor.opacity(0.05) : Color.clear)
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
