import ARKit
import RealityKit
import SwiftUI

private struct ExportRequest: Identifiable {
    let folderURL: URL
    var id: URL { folderURL }
}

struct ContentView: View {
    @Environment(\.scenePhase) private var scenePhase
    @StateObject private var recordingCoordinator = RecordingCoordinator()
    @StateObject private var experimentSettings = ExperimentServerSettings()
    @StateObject private var remoteControlManager = RemoteControlManager()
    @StateObject private var liveKitPreviewManager = LiveKitPreviewManager()
    @StateObject private var thermalMonitor = ThermalMonitor()
    @StateObject private var diagnostics = AppDiagnostics.shared
    @State private var shareItems: [Any] = []
    @State private var pendingShareItems: [Any]?
    @State private var isShowingShareSheet = false
    @State private var showStorageSheet = false
    @State private var showUploadSheet = false
    @State private var exportRequest: ExportRequest?
    @State private var showGestureGuide = false
    @State private var selectedAppTab: SandStoriesTab = .capture
    private let shareExportManager = ShareExportManager()

    var body: some View {
        adaptiveTabView
            .tint(Color(red: 0.94, green: 0.70, blue: 0.28))
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
            .sheet(item: $exportRequest, onDismiss: presentPendingShareSheet) { request in
                ExportSessionPreviewSheet(sessionFolderName: request.folderURL.lastPathComponent) {
                    Task { await exportAndPresentShare(folder: request.folderURL) }
                }
                .presentationDetents([.medium, .large])
                .presentationDragIndicator(.visible)
                .presentationCornerRadius(28)
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
                    thermalMonitor.evaluateForActiveSession()
                } else {
                    thermalMonitor.resetForNextSession()
                    liveKitPreviewManager.resetThermalSuspension()
                }
            }
            .onAppear { diagnostics.recordLaunchContext() }
            .task(id: networkConfiguration) {
                remoteControlManager.stop()
                liveKitPreviewManager.disconnect()
                guard scenePhase == .active else { return }
                do { try await Task.sleep(nanoseconds: 400_000_000) } catch { return }
                remoteControlManager.start(settings: experimentSettings, coordinator: recordingCoordinator)
                await liveKitPreviewManager.connect(settings: experimentSettings)
            }
            .onDisappear {
                remoteControlManager.stop()
                liveKitPreviewManager.disconnect()
            }
            .onChange(of: selectedAppTab) { _, tab in
                diagnostics.record("Selected tab: \(tab.diagnosticsName)", category: "Navigation")
            }
    }

    private var networkConfiguration: String {
        [String(experimentSettings.enabled), experimentSettings.serverURL,
         experimentSettings.deviceToken, experimentSettings.deviceName,
         String(experimentSettings.previewEnabled), String(describing: scenePhase)].joined(separator: "\n")
    }

    @ViewBuilder
    private var adaptiveTabView: some View {
        if #available(iOS 26.0, *) {
            // The system tab bar renders as floating Liquid Glass automatically on iOS 26.
            // The record controls intentionally live in the capture tab itself (safeAreaInset),
            // NOT in tabViewBottomAccessory: conditional accessories collapse and hide the
            // primary capture action (regressed twice — see PR #11 / PR #13).
            appTabView
                .tabBarMinimizeBehavior(.onScrollDown)
        } else {
            appTabView
        }
    }

    private var appTabView: some View {
        TabView(selection: $selectedAppTab) {
            captureTab
                .tabItem {
                    Label("Capture", systemImage: "camera.fill")
                }
                .tag(SandStoriesTab.capture)

            SessionsTabView(
                destinationLabel: recordingCoordinator.destinationLabel,
                lastSessionFolderURL: recordingCoordinator.lastSessionFolderURL,
                isRecording: recordingCoordinator.isCaptureRecording,
                isSaving: recordingCoordinator.isSavingSession,
                onChooseStorage: {
                    guard !recordingCoordinator.isCaptureRecording, !recordingCoordinator.isSavingSession else { return }
                    showStorageSheet = true
                },
                onExportLastSession: presentLastSessionExport
            )
            .tabItem {
                Label("Sessions", systemImage: "rectangle.stack.fill")
            }
            .tag(SandStoriesTab.sessions)

            SettingsTabView(
                recordingCoordinator: recordingCoordinator,
                diagnostics: diagnostics,
                onChooseStorage: {
                    guard !recordingCoordinator.isCaptureRecording, !recordingCoordinator.isSavingSession else { return }
                    showStorageSheet = true
                },
                onShowUploadSettings: {
                    guard !recordingCoordinator.isCaptureRecording, !recordingCoordinator.isSavingSession else { return }
                    showUploadSheet = true
                }
            )
            .tabItem {
                Label("Settings", systemImage: "gearshape.fill")
            }
            .tag(SandStoriesTab.settings)
        }
    }

    private var captureTab: some View {
        captureCanvas
            .safeAreaInset(edge: .bottom, spacing: 0) {
                captureControlsBar
            }
    }

    @ViewBuilder
    private var captureControlsBar: some View {
        let bar = captureAccessory
            .frame(maxWidth: .infinity)
            .padding(.horizontal, 20)
            .padding(.vertical, 10)
            .onAppear {
                diagnostics.recordOnce(
                    key: "record-controls-bar",
                    category: "Navigation",
                    message: "Record controls bar appeared"
                )
            }

        if #available(iOS 26.0, *) {
            // No darkening gradient: it interferes with the Liquid Glass scroll edge effect.
            bar
        } else {
            bar
                .background {
                    LinearGradient(
                        colors: [.clear, Color.black.opacity(0.30)],
                        startPoint: .top,
                        endPoint: .bottom
                    )
                    .allowsHitTesting(false)
                }
        }
    }

    private var captureCanvas: some View {
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
            }
            .padding(.top, 8)
            .zIndex(2)

            if recordingCoordinator.isSavingSession {
                savingOverlay
                    .zIndex(3)
                    .transition(.opacity)
            }

            if let feedback = recordingCoordinator.gestureFeedback {
                gestureFeedbackPopup(feedback.message)
                    .id(feedback.id)
                    .zIndex(4)
                    .transition(.opacity.combined(with: .move(edge: .top)))
            }
        }
        .animation(.easeInOut(duration: 0.2), value: recordingCoordinator.gestureFeedback)
        .preferredColorScheme(.dark)
    }

    private var savingOverlay: some View {
        ZStack {
            Color.black.opacity(0.38)
                .ignoresSafeArea()

            VStack(spacing: 16) {
                ProgressView()
                    .controlSize(.large)
                    .tint(Color.accentColor)

                VStack(spacing: 6) {
                    Text("Saving Session…")
                        .font(.title3.weight(.bold))
                        .foregroundStyle(Color(uiColor: .label))

                    Text(recordingCoordinator.savingStatusMessage ?? "Please wait while session data is saved.")
                        .font(.subheadline)
                        .foregroundStyle(Color(uiColor: .secondaryLabel))
                        .multilineTextAlignment(.center)
                }

                Text("Do not close app or disconnect external SSD")
                    .font(.caption2.weight(.semibold))
                    .foregroundStyle(Color.accentColor)
                    .padding(.horizontal, 12)
                    .padding(.vertical, 5)
                    .background(Color.accentColor.opacity(0.12))
                    .clipShape(Capsule())
            }
            .padding(24)
            .frame(maxWidth: 320)
            .glassPanel(cornerRadius: 24, blurStyle: .systemUltraThinMaterial, shadowRadius: 18, shadowYOffset: 6)
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

                    if !recordingCoordinator.isCaptureRecording && !recordingCoordinator.isSavingSession && !recordingCoordinator.isBenchmarkRunning && !recordingCoordinator.isDepthDiagnosticRunning {
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

            if let success = recordingCoordinator.saveSuccessBanner {
                statusGlassText("✓ " + success)
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
                gestureName: "Yo Gesture (hold 2s)",
                actionDescription: "Pause / Resume Recording",
                isEnabled: $recordingCoordinator.isPauseGestureEnabled
            )
            InteractiveGestureRow(
                icon: "camera.fill",
                gestureName: "Cover Camera (hold 3s)",
                actionDescription: "Stop and Save Recording",
                isEnabled: $recordingCoordinator.isStopGestureEnabled
            )
            InteractiveGestureRow(
                icon: "hand.point.up.left.fill",
                gestureName: "Pinch and Hold (2s)",
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
            guard !recordingCoordinator.isCaptureRecording, !recordingCoordinator.isSavingSession else { return }
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
        .disabled(recordingCoordinator.isCaptureRecording || recordingCoordinator.isSavingSession)
        .opacity((recordingCoordinator.isCaptureRecording || recordingCoordinator.isSavingSession) ? 0.82 : 1)
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
            if recordingCoordinator.isSavingSession {
                ProgressView()
                    .controlSize(.mini)
                    .tint(Color.accentColor)
                Text("Saving…")
                    .font(.caption2.weight(.bold))
                    .foregroundStyle(Color.accentColor)
            } else if recordingCoordinator.isCaptureRecording {
                TimelineView(.periodic(from: .now, by: 1)) { timeline in
                    Text(recordingElapsedText(at: timeline.date))
                        .font(.caption.monospacedDigit().weight(.semibold))
                        .foregroundStyle(Color(uiColor: .label))
                }
                Text(recordingCoordinator.isCapturePaused ? "Paused" : "Recording")
                    .font(.caption2.weight(.medium))
                    .foregroundStyle(
                        recordingCoordinator.isCapturePaused
                            ? Color(red: 0.94, green: 0.70, blue: 0.28)
                            : Color(uiColor: .secondaryLabel)
                    )
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
        if recordingCoordinator.isSavingSession {
            return "Saving session to storage"
        }
        guard recordingCoordinator.isCaptureRecording else {
            return "Ready, not recording"
        }

        let state = recordingCoordinator.isCapturePaused ? "Paused" : "Recording"
        return "\(state), elapsed \(recordingElapsedText(at: Date()))"
    }

    private func formattedDuration(seconds: TimeInterval) -> String {
        let totalSeconds = max(0, Int(seconds))
        let minutes = totalSeconds / 60
        let remainder = totalSeconds % 60
        return String(format: "%d:%02d", minutes, remainder)
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
            !recordingCoordinator.isSavingSession &&
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

    private func gestureFeedbackPopup(_ message: String) -> some View {
        Text(message)
            .font(.subheadline.weight(.semibold))
            .foregroundStyle(Color(uiColor: .label))
            .lineLimit(1)
            .minimumScaleFactor(0.8)
            .padding(.horizontal, 16)
            .padding(.vertical, 10)
            .glassPanel(cornerRadius: 18, blurStyle: .systemThinMaterial, shadowRadius: 10, shadowYOffset: 4)
            .padding(.horizontal, 20)
            .padding(.top, 72)
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
            .allowsHitTesting(false)
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

    // MARK: - Contextual capture controls

    @ViewBuilder
    private var captureAccessory: some View {
        if #available(iOS 26.0, *) {
            // Shared sampling region for nearby glass. Keep the blend spacing small so the
            // REC pill and the stop button render as separate shapes instead of merging.
            GlassEffectContainer(spacing: 4) {
                captureAccessoryContent
            }
        } else {
            captureAccessoryContent
        }
    }

    @ViewBuilder
    private var captureAccessoryContent: some View {
        if recordingCoordinator.isSavingSession {
            savingControlAccessory
                .transition(.scale(scale: 0.95).combined(with: .opacity))
        } else if recordingCoordinator.isCaptureRecording {
            recordingControlAccessory
                .transition(.move(edge: .bottom).combined(with: .opacity))
        } else {
            idleRecordAccessory
                .transition(.scale(scale: 0.92).combined(with: .opacity))
        }
    }

    private var savingControlAccessory: some View {
        HStack(spacing: 10) {
            ProgressView()
                .controlSize(.small)
                .tint(Color.accentColor)
            Text("SAVING RECORDING…")
                .font(.caption.weight(.bold))
                .foregroundStyle(Color.white)
        }
        .padding(.horizontal, 22)
        .frame(height: 52)
        .liquidGlassDock()
        .accessibilityElement(children: .combine)
        .accessibilityLabel("Saving recording in progress")
    }

    private var idleRecordAccessory: some View {
        let isDisabled = recordingCoordinator.isSavingSession || recordingCoordinator.isBenchmarkRunning || recordingCoordinator.isDepthDiagnosticRunning

        return Button {
            diagnostics.record("Expanded record button tapped", category: "Capture")
            Task {
                await recordingCoordinator.toggleRecording()
            }
        } label: {
            ZStack {
                Circle()
                    .stroke(Color.white.opacity(0.96), lineWidth: 3)
                    .frame(width: 66, height: 66)
                Circle()
                    .fill(Color(uiColor: .systemRed))
                    .frame(width: 54, height: 54)
            }
            .frame(width: 72, height: 72)
            .interactiveGlassCircle()
            .padding(.vertical, 4)
            .contentShape(Circle())
        }
        .buttonStyle(.plain)
        .disabled(isDisabled)
        .opacity(isDisabled ? 0.42 : 1)
        .accessibilityLabel("Start session recording")
    }

    private var recordingControlAccessory: some View {
        TimelineView(.periodic(from: .now, by: 1)) { timeline in
            VStack(spacing: 16) {
                HStack(spacing: 7) {
                    Image(systemName: recordingCoordinator.isCapturePaused ? "pause.fill" : "circle.fill")
                        .font(.system(size: 8, weight: .bold))
                        .foregroundStyle(
                            recordingCoordinator.isCapturePaused
                                ? Color(red: 0.94, green: 0.70, blue: 0.28)
                                : Color(uiColor: .systemRed)
                        )
                    Text(recordingCoordinator.isCapturePaused ? "PAUSED" : "REC")
                        .font(.caption2.weight(.bold))
                        .foregroundStyle(Color.white)
                    Text(recordingElapsedText(at: timeline.date))
                        .font(.caption.monospacedDigit().weight(.semibold))
                        .foregroundStyle(Color.white.opacity(0.92))
                }
                .padding(.horizontal, 12)
                .frame(height: 28)
                .liquidGlassDock()
                .accessibilityElement(children: .combine)
                .accessibilityLabel(
                    "\(recordingCoordinator.isCapturePaused ? "Paused" : "Recording"), elapsed \(recordingElapsedText(at: timeline.date))"
                )

                HStack(spacing: 30) {
                    Button {
                        Task {
                            await recordingCoordinator.togglePauseCaptureSession()
                        }
                    } label: {
                        ZStack {
                            Circle()
                                .stroke(Color.white.opacity(0.82), lineWidth: 1.5)
                                .frame(width: 48, height: 48)
                            Image(systemName: recordingCoordinator.isCapturePaused ? "play.fill" : "pause.fill")
                                .font(.system(size: 19, weight: .semibold))
                                .foregroundStyle(Color.white)
                                .offset(x: recordingCoordinator.isCapturePaused ? 1 : 0)
                        }
                        .frame(width: 54, height: 54)
                        .interactiveGlassCircle(fallbackFillOpacity: 0.56)
                        .contentShape(Circle())
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel(
                        recordingCoordinator.isCapturePaused
                            ? "Resume session recording"
                            : "Pause session recording"
                    )

                    Button {
                        Task {
                            await recordingCoordinator.toggleRecording()
                        }
                    } label: {
                        ZStack {
                            Circle()
                                .stroke(Color.white.opacity(0.96), lineWidth: 3)
                                .frame(width: 66, height: 66)
                            RoundedRectangle(cornerRadius: 7, style: .continuous)
                                .fill(Color(uiColor: .systemRed))
                                .frame(width: 34, height: 34)
                        }
                        .frame(width: 72, height: 72)
                        .interactiveGlassCircle()
                        .contentShape(Circle())
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel("Stop and save session recording")

                    Color.clear
                        .frame(width: 54, height: 54)
                        .accessibilityHidden(true)
                }
            }
            .frame(maxWidth: .infinity)
            .accessibilityElement(children: .contain)
        }
    }

    private func recordingElapsedText(at _: Date) -> String {
        formattedDuration(seconds: recordingCoordinator.recordingElapsedSeconds())
    }

    // MARK: - Export

    private func presentLastSessionExport() {
        guard let folder = recordingCoordinator.lastSessionFolderURL else { return }
        exportRequest = ExportRequest(folderURL: folder)
    }

    private func presentPendingShareSheet() {
        guard let items = pendingShareItems else { return }
        shareItems = items
        pendingShareItems = nil
        isShowingShareSheet = true
    }

    private func exportAndPresentShare(folder: URL) async {
        do {
            let zipURL = try await shareExportManager.zipSessionFolder(folder)
            await MainActor.run {
                pendingShareItems = [zipURL]
                exportRequest = nil
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
        return arView
    }

    @MainActor
    func updateUIView(_ uiView: ARView, context: Context) {
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

        if isCaptureRecording, supportsSceneDepth {
            configuration.frameSemantics.insert(.sceneDepth)
        }
        if isCaptureRecording, performanceMode == .fullQuality, supportsSmoothedSceneDepth {
            configuration.frameSemantics.insert(.smoothedSceneDepth)
        }
        if isCaptureRecording, !supportsSceneDepth, supportsSmoothedSceneDepth {
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

        arView.session.run(configuration, options: options)
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
