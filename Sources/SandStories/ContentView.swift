import ARKit
import RealityKit
import SwiftUI

struct ContentView: View {
    @StateObject private var recordingCoordinator = RecordingCoordinator()
    @State private var shareItems: [Any] = []
    @State private var isShowingShareSheet = false
    @State private var showStorageSheet = false
    @State private var showExportSheet = false
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
                        Text("Tripod Gestures")
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
                    
                    VStack(alignment: .leading, spacing: 12) {
                        GestureGuideRow(icon: "hand.raised.fill", gestureName: "Open Palm (hold 1s)", actionDescription: "Pause / Resume Recording")
                        GestureGuideRow(icon: "hand.wave.fill", gestureName: "Wave Hand", actionDescription: "Start / Stop Session")
                        GestureGuideRow(icon: "hand.point.up.left.fill", gestureName: "Two-Finger Double Tap", actionDescription: "Mark Segment")
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
                .frame(maxWidth: 290)
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
        .animation(.spring(duration: 0.35, bounce: 0.22), value: recordingCoordinator.isCaptureRecording)
    }

    // MARK: - Top

    private var topChrome: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .top, spacing: 12) {
                destinationPill
                Spacer(minLength: 8)
                gestureGuideButton
                sessionStatusHUD
            }
            .padding(.horizontal, 16)

            locationOverlay
                .padding(.horizontal, 16)

            if let warn = recordingCoordinator.warningBanner {
                Text(warn)
                    .font(.caption)
                    .foregroundStyle(Color(uiColor: .secondaryLabel))
                    .multilineTextAlignment(.leading)
                    .padding(.horizontal, 14)
                    .padding(.vertical, 10)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .glassPanel(cornerRadius: 14, blurStyle: .systemThinMaterial, shadowRadius: 10, shadowYOffset: 4)
                    .padding(.horizontal, 16)
                    .transition(.opacity.combined(with: .move(edge: .top)))
            }

            if let summary = recordingCoordinator.benchmarkSummary {
                Text(summary)
                    .font(.caption.monospacedDigit())
                    .foregroundStyle(Color(uiColor: .secondaryLabel))
                    .multilineTextAlignment(.leading)
                    .padding(.horizontal, 14)
                    .padding(.vertical, 10)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .glassPanel(cornerRadius: 14, blurStyle: .systemThinMaterial, shadowRadius: 10, shadowYOffset: 4)
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
                    .lineLimit(2)
                    .multilineTextAlignment(.leading)
                Spacer(minLength: 0)
            }
            .padding(.leading, 12)
            .padding(.trailing, 14)
            .padding(.vertical, 10)
            .frame(minHeight: 44)
            .frame(maxWidth: 280, alignment: .leading)
            .glassPanel(cornerRadius: 22)
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
        .padding(.vertical, 10)
        .glassPanel(cornerRadius: 16, blurStyle: .systemThinMaterial, shadowRadius: 12, shadowYOffset: 5)
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
        Text(recordingCoordinator.locationCaptureManager.coordinateDisplay)
            .font(.caption)
            .foregroundStyle(Color(uiColor: .secondaryLabel))
            .padding(.horizontal, 12)
            .padding(.vertical, 8)
            .frame(maxWidth: .infinity, alignment: .leading)
            .glassPanel(cornerRadius: 12, blurStyle: .systemUltraThinMaterial, shadowRadius: 8, shadowYOffset: 3)
            .allowsHitTesting(false)
    }

    // MARK: - Bottom

    private var bottomChrome: some View {
        VStack(spacing: 20) {
            recordFloatingButton

            HStack(spacing: 12) {
                clearToolbarButton
                benchmarkToolbarButton
                shareToolbarButton
            }
            .padding(.horizontal, 14)
            .padding(.vertical, 12)
            .glassPanel(cornerRadius: 26, blurStyle: .systemThinMaterial, shadowRadius: 16, shadowYOffset: 8)
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
                    .frame(width: 80, height: 80)
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
                            .stroke(Color(uiColor: .label).opacity(0.2), lineWidth: 1)
                    }
                    .shadow(color: Color(uiColor: .label).opacity(0.14), radius: 18, y: 8)

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
            .frame(width: 80, height: 80)
        }
        .buttonStyle(.plain)
        .frame(minWidth: 44, minHeight: 44)
        .accessibilityLabel(recordingCoordinator.isCaptureRecording ? "Stop session recording" : "Start session recording")
        .disabled(recordingCoordinator.isBenchmarkRunning)
        .opacity(recordingCoordinator.isBenchmarkRunning ? 0.5 : 1)
    }

    private var clearToolbarButton: some View {
        Button {
            Task {
                await recordingCoordinator.handPoseManager.clearStrokes()
            }
        } label: {
            Label("Clear", systemImage: "paintbrush.pointed")
                .font(.subheadline.weight(.semibold))
                .labelStyle(.titleAndIcon)
                .foregroundStyle(Color(uiColor: .label))
                .frame(maxWidth: .infinity)
                .frame(minHeight: 44)
        }
        .buttonStyle(.plain)
        .accessibilityLabel("Clear strokes")
    }

    private var benchmarkToolbarButton: some View {
        Button {
            Task {
                await recordingCoordinator.runDepthBenchmark()
            }
        } label: {
            Label(recordingCoordinator.isBenchmarkRunning ? "Running" : "Benchmark", systemImage: "speedometer")
                .font(.subheadline.weight(.semibold))
                .labelStyle(.titleAndIcon)
                .foregroundStyle(recordingCoordinator.isBenchmarkRunning ? Color(uiColor: .secondaryLabel) : Color.accentColor)
                .frame(maxWidth: .infinity)
                .frame(minHeight: 44)
        }
        .buttonStyle(.plain)
        .disabled(recordingCoordinator.isCaptureRecording || recordingCoordinator.isBenchmarkRunning)
        .opacity(recordingCoordinator.isCaptureRecording ? 0.45 : 1)
        .accessibilityLabel("Run 15 second depth capture benchmark")
    }

    private var shareToolbarButton: some View {
        Button {
            Task {
                guard let folder = recordingCoordinator.lastSessionFolderURL else {
                    print("Share: no session folder yet — record a session first.")
                    return
                }
                await MainActor.run {
                    exportFolderURL = folder
                    showExportSheet = true
                }
            }
        } label: {
            Label("Share", systemImage: "square.and.arrow.up")
                .font(.subheadline.weight(.semibold))
                .labelStyle(.titleAndIcon)
                .foregroundStyle(Color.accentColor)
                .frame(maxWidth: .infinity)
                .frame(minHeight: 44)
        }
        .buttonStyle(.plain)
        .accessibilityLabel("Share last session")
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
        .accessibilityLabel("Show tripod gestures guide")
    }
}

struct GestureGuideRow: View {
    let icon: String
    let gestureName: String
    let actionDescription: String
    
    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            Image(systemName: icon)
                .font(.title3)
                .foregroundStyle(Color.accentColor)
                .frame(width: 28)
            VStack(alignment: .leading, spacing: 2) {
                Text(gestureName)
                    .font(.caption.weight(.bold))
                    .foregroundStyle(Color(uiColor: .label))
                Text(actionDescription)
                    .font(.caption2)
                    .foregroundStyle(Color(uiColor: .secondaryLabel))
            }
        }
    }
}
