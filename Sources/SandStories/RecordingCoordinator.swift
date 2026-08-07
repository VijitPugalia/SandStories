import ARKit
import Foundation
import ImageIO
import SwiftUI

/// Owns capture session lifecycle: manifest, depth/RGB paths, audio, strokes, tray + object hooks, storage.
@MainActor
final class RecordingCoordinator: ObservableObject {
    let depthCaptureManager = DepthCaptureManager()
    let handPoseManager = HandPoseCaptureManager()
    let framePipeline = SessionFramePipeline()
    let storageStore = StorageDestinationStore()
    let audioRecorder = SessionAudioRecorder()
    let captureSession = CaptureSessionController()
    let locationCaptureManager = LocationCaptureManager()
    let uploadSettings = UploadSettingsStore()
    let uploadManager = SessionUploadManager()
    let zoomController = CameraZoomController()

    private let objectDetector: any StoryObjectDetecting = StubStoryObjectDetector()

    /// Mean absolute delta on 32×32 downsampled UInt16 depth; skip save when below this (configurable).
    var depthDeltaThresholdMeanU16: Float = 0

    @Published private(set) var isCaptureRecording = false
    @Published private(set) var isCapturePaused = false
    @Published var destinationLabel: String = "Saving to: Internal"
    @Published var warningBanner: String?
    @Published var showingFolderPicker = false
    @Published private(set) var lastSessionFolderURL: URL?
    @Published private(set) var isBenchmarkRunning = false
    @Published private(set) var isDepthDiagnosticRunning = false
    @Published private(set) var benchmarkSummary: String?
    @Published private(set) var depthDiagnosticSummary: String?
    @Published var isDepthDiagnosticRawOnly: Bool = false
    @Published private(set) var uploadStatus: String?
    @Published private(set) var capturePerformanceMode: CapturePerformanceMode = .fullQuality
    @Published var isMeshVisualizationEnabled: Bool = UserDefaults.standard.object(forKey: "isMeshVisualizationEnabled") as? Bool ?? false {
        didSet {
            UserDefaults.standard.set(isMeshVisualizationEnabled, forKey: "isMeshVisualizationEnabled")
        }
    }

    @Published var isPauseGestureEnabled: Bool = true {
        didSet {
            UserDefaults.standard.set(isPauseGestureEnabled, forKey: "isPauseGestureEnabled")
            handPoseManager.isPauseGestureEnabled = isPauseGestureEnabled
        }
    }
    @Published var isStopGestureEnabled: Bool = true {
        didSet {
            UserDefaults.standard.set(isStopGestureEnabled, forKey: "isStopGestureEnabled")
            handPoseManager.isStopGestureEnabled = isStopGestureEnabled
        }
    }
    @Published var isMarkGestureEnabled: Bool = true {
        didSet {
            UserDefaults.standard.set(isMarkGestureEnabled, forKey: "isMarkGestureEnabled")
            handPoseManager.isMarkGestureEnabled = isMarkGestureEnabled
        }
    }

    private var externalScopedURL: URL?
    private var trayDetectionLocked = false
    private var auxiliaryFrameCounter = 0
    private var pendingStrokeAlignment = false
    private var audioStartMonotonic: Double = 0
    private var usedExternalForCurrentSession = false
    private var activeDepthDiagnosticProfile: String?

    private enum StopReason {
        case manual
        case remote
        case gesture
        case thermal
    }

    init() {
        let pauseEnabled = UserDefaults.standard.object(forKey: "isPauseGestureEnabled") as? Bool ?? true
        let stopEnabled = UserDefaults.standard.object(forKey: "isStopGestureEnabled") as? Bool ?? true
        let markEnabled = UserDefaults.standard.object(forKey: "isMarkGestureEnabled") as? Bool ?? true
        
        self.isPauseGestureEnabled = pauseEnabled
        self.isStopGestureEnabled = stopEnabled
        self.isMarkGestureEnabled = markEnabled
        
        self.handPoseManager.isPauseGestureEnabled = pauseEnabled
        self.handPoseManager.isStopGestureEnabled = stopEnabled
        self.handPoseManager.isMarkGestureEnabled = markEnabled

        framePipeline.coordinator = self
        depthCaptureManager.zoomMetadataProvider = { [weak zoomController] in
            zoomController?.captureMetadata()
        }
        refreshDestinationLabel()
        
        handPoseManager.onGestureCommand = { [weak self] command in
            guard let self else { return }
            Task {
                switch command {
                case .start:
                    if self.isCaptureRecording {
                        await self.stopActiveCaptureSession(reason: .gesture)
                    } else {
                        await self.startCaptureSession(recordAudio: true)
                    }
                case .stop:
                    if self.isCaptureRecording {
                        await self.stopActiveCaptureSession(reason: .gesture)
                    }
                case .pause:
                    if self.isCapturePaused {
                        await self.resumeCaptureSession()
                    } else {
                        await self.pauseCaptureSession()
                    }
                case .resume:
                    await self.resumeCaptureSession()
                case .markSegment:
                    await self.markSegment()
                }
            }
        }
    }

    func refreshDestinationLabel() {
        switch storageStore.currentKind() {
        case .internalDocuments:
            destinationLabel = "Saving to: Internal"
        case .externalBookmark:
            if let name = storageStore.externalDisplayName() {
                destinationLabel = "Saving to: SSD — \(name)"
            } else {
                destinationLabel = "Saving to: External folder"
            }
        }
    }

    func selectInternalDestination() {
        storageStore.setInternal()
        refreshDestinationLabel()
    }

    func requestExternalFolderPicker() {
        showingFolderPicker = true
    }

    func handleExternalFolderPicked(_ url: URL) {
        showingFolderPicker = false
        do {
            let data = try url.bookmarkData(
                options: [],
                includingResourceValuesForKeys: nil,
                relativeTo: nil
            )
            storageStore.setExternalBookmark(data: data, displayName: url.lastPathComponent)
            url.stopAccessingSecurityScopedResource()
            refreshDestinationLabel()
        } catch {
            warningBanner = "Could not save folder access; using Internal."
            storageStore.setInternal()
            refreshDestinationLabel()
        }
    }

    func handleFolderPickerCancelled() {
        showingFolderPicker = false
        warningBanner = "Folder not selected; saving to Internal."
        storageStore.setInternal()
        refreshDestinationLabel()
    }

    /// Toggle packaged session recording (manifest + aligned modalities).
    func toggleRecording() async {
        if isCaptureRecording {
            await stopActiveCaptureSession(reason: .manual)
        } else {
            guard !isBenchmarkRunning, !isDepthDiagnosticRunning else { return }
            await startCaptureSession()
        }
    }

    func startFromRemote(recordAudio: Bool = true) async {
        guard !isCaptureRecording, !isBenchmarkRunning, !isDepthDiagnosticRunning else { return }
        await startCaptureSession(recordAudio: recordAudio)
    }

    func stopFromRemote() async {
        guard isCaptureRecording else { return }
        await stopActiveCaptureSession(reason: .remote)
    }

    func reduceLoadForThermal() {
        guard isCaptureRecording else { return }
        capturePerformanceMode = .thermalReduced
        isMeshVisualizationEnabled = false
        depthCaptureManager.updateCapturePolicy(
            targetCaptureFPS: 15,
            capturesSmoothedDepth: false,
            captureProfile: "thermal_reduced",
            enabledFrameSemantics: ["sceneDepth"]
        )
        handPoseManager.setTargetFrameRate(8)
        warningBanner = "Reduced mode: raw LiDAR and lighter hand tracking until this session ends."
    }

    func stopForThermal() async {
        guard isCaptureRecording else { return }
        await stopActiveCaptureSession(reason: .thermal)
    }

    func uploadLastSessionFromRemote() async {
        guard let folder = lastSessionFolderURL, let endpoint = uploadSettings.endpointURL() else { return }
        uploadStatus = "Uploading session..."
        do {
            try await uploadManager.uploadSessionFolder(folder, to: endpoint)
            uploadStatus = "Upload complete"
        } catch {
            uploadStatus = "Upload failed: \(error.localizedDescription)"
        }
    }

    func runDepthBenchmark() async {
        guard !isCaptureRecording, !isBenchmarkRunning, !isDepthDiagnosticRunning else { return }

        isBenchmarkRunning = true
        benchmarkSummary = "Benchmark running for 15 seconds..."
        warningBanner = nil

        await depthCaptureManager.resetBenchmarkMetrics()
        let start = Date()
        await startCaptureSession(recordAudio: false)

        guard isCaptureRecording else {
            isBenchmarkRunning = false
            benchmarkSummary = "Benchmark could not start."
            return
        }

        do {
            try await Task.sleep(nanoseconds: 15_000_000_000)
        } catch {
            // If the task is cancelled, stop cleanly and still report what was captured.
        }

        guard isBenchmarkRunning else { return }
        if isCaptureRecording {
            await stopCaptureSession()
        }

        let elapsed = Date().timeIntervalSince(start)
        let snapshot = await depthCaptureManager.benchmarkSnapshot()
        let summary = snapshot.summary(elapsedSeconds: elapsed)
        benchmarkSummary = summary
        warningBanner = "Benchmark complete. \(summary)"
        print(summary)
        isBenchmarkRunning = false
    }

    func runDepthDiagnostic() async {
        guard !isCaptureRecording, !isBenchmarkRunning, !isDepthDiagnosticRunning else { return }

        let durationSeconds: Double = 20
        let capturesSmoothed = !isDepthDiagnosticRawOnly
        let profile = capturesSmoothed ? "depth_diagnostic_raw_plus_smoothed" : "depth_diagnostic_raw_only"

        isDepthDiagnosticRunning = true
        depthDiagnosticSummary = "Depth diagnostic running for 20 seconds..."
        warningBanner = nil

        await depthCaptureManager.resetBenchmarkMetrics()
        let start = Date()
        await startCaptureSession(
            recordAudio: false,
            forcedDeltaThresholdMeanU16: 0,
            capturesSmoothedDepth: capturesSmoothed,
            captureProfile: profile,
            diagnosticDurationSeconds: durationSeconds
        )

        guard isCaptureRecording else {
            isDepthDiagnosticRunning = false
            depthDiagnosticSummary = "Depth diagnostic could not start."
            return
        }

        do {
            try await Task.sleep(nanoseconds: UInt64(durationSeconds * 1_000_000_000))
        } catch {
            // Stop cleanly and report whatever was captured.
        }

        guard isDepthDiagnosticRunning else { return }
        if isCaptureRecording {
            await stopCaptureSession()
        }

        let elapsed = Date().timeIntervalSince(start)
        let snapshot = await depthCaptureManager.benchmarkSnapshot()
        let summary = snapshot.diagnosticSummary(elapsedSeconds: elapsed, profile: profile)
        depthDiagnosticSummary = summary
        warningBanner = "Depth diagnostic complete. \(summary)"
        print(summary)
        isDepthDiagnosticRunning = false
    }

    func togglePauseCaptureSession() async {
        guard isCaptureRecording else { return }
        if isCapturePaused {
            await resumeCaptureSession()
        } else {
            await pauseCaptureSession()
        }
    }

    func pauseCaptureSession() async {
        guard isCaptureRecording, !isCapturePaused else { return }
        isCapturePaused = true
        audioRecorder.pauseRecording()
        depthCaptureManager.setRecording(false)
        await handPoseManager.setPaused(true)
        await handPoseManager.clearStrokes()
    }

    func resumeCaptureSession() async {
        guard isCaptureRecording, isCapturePaused else { return }
        isCapturePaused = false
        audioRecorder.resumeRecording()
        depthCaptureManager.setRecording(true)
        await handPoseManager.setPaused(false)
    }

    func markSegment() async {
        guard isCaptureRecording else { return }
        try? await captureSession.markSegment()
    }

    func processAuxiliaryCaptureFrame(arTimestamp: TimeInterval, capturedImage: PixelBufferBox) async {
        guard isCaptureRecording, !isCapturePaused else { return }
        await captureSession.noteFirstARFrameIfNeeded(arTimestamp)
        auxiliaryFrameCounter += 1

        if pendingStrokeAlignment {
            pendingStrokeAlignment = false
            await handPoseManager.alignStrokeSessionStart(arTimestamp: arTimestamp)
        }

        if auxiliaryFrameCounter % 45 == 0 {
            let mono = await captureSession.monotonicElapsedSeconds()
            if let tray = TrayBoundaryDetector.detectCorners(
                pixelBuffer: capturedImage.pixelBuffer,
                orientation: CGImagePropertyOrientation.right
            ) {
                try? await captureSession.appendBoundarySample(
                    .init(
                        arTimestamp: arTimestamp,
                        monotonicElapsedSeconds: mono,
                        confidence: tray.confidence,
                        cornersNormalized: tray.corners
                    )
                )
                if !trayDetectionLocked {
                    trayDetectionLocked = true
                    try? await captureSession.setTrayBoundary(
                        .init(status: "detected", cornersNormalized: tray.corners, note: "saturation corner heuristic; Vision-style normalized coords")
                    )
                }
            } else {
                try? await captureSession.appendBoundarySample(
                    .init(
                        arTimestamp: arTimestamp,
                        monotonicElapsedSeconds: mono,
                        confidence: 0.0,
                        cornersNormalized: nil
                    )
                )
            }
        }

        if auxiliaryFrameCounter % 28 == 0 {
            let mono = await captureSession.monotonicElapsedSeconds()
            let recs = await objectDetector.detect(
                pixelBuffer: capturedImage.pixelBuffer,
                orientation: .right,
                arTimestamp: arTimestamp,
                monotonicElapsedSeconds: mono
            )
            for r in recs {
                try? await captureSession.appendObjectLine(r)
            }
        }
    }

    // MARK: - Private

    private func startCaptureSession(
        recordAudio: Bool = true,
        forcedDeltaThresholdMeanU16: Float? = nil,
        capturesSmoothedDepth: Bool = true,
        captureProfile: String = "standard",
        diagnosticDurationSeconds: Double? = nil
    ) async {
        warningBanner = nil
        capturePerformanceMode = .fullQuality
        let sessionId = UUID()
        let fm = FileManager.default
        let captureDeltaThreshold = forcedDeltaThresholdMeanU16 ?? depthDeltaThresholdMeanU16
        let enabledSemantics = capturesSmoothedDepth ? ["sceneDepth", "smoothedSceneDepth"] : ["sceneDepth"]
        let diagnosticInfo = diagnosticDurationSeconds.map {
            CaptureSessionManifest.DepthDiagnosticInfo(
                enabled: true,
                profile: captureProfile,
                durationSeconds: $0,
                capturesSmoothedDepth: capturesSmoothedDepth,
                forcedDeltaThresholdU16: captureDeltaThreshold,
                enabledFrameSemantics: enabledSemantics,
                counters: nil
            )
        }
        activeDepthDiagnosticProfile = diagnosticInfo?.profile

        var baseURL: URL
        var securityScoped = false
        usedExternalForCurrentSession = false

        if storageStore.currentKind() == .externalBookmark {
            do {
                if let resolved = try storageStore.resolveExternalFolderURL() {
                    if resolved.startAccessingSecurityScopedResource() {
                        externalScopedURL = resolved
                        baseURL = resolved
                        securityScoped = true
                        usedExternalForCurrentSession = true
                    } else {
                        fallbackToInternalStorage(reason: "Could not access external folder.")
                        baseURL = internalSessionsRoot()
                    }
                } else {
                    fallbackToInternalStorage(reason: "External folder bookmark expired; pick again.")
                    baseURL = internalSessionsRoot()
                }
            } catch {
                fallbackToInternalStorage(reason: "External storage unavailable.")
                baseURL = internalSessionsRoot()
            }
        } else {
            baseURL = internalSessionsRoot()
        }

        let folderName = "session_\(sessionId.uuidString)"
        let sessionFolder = baseURL.appendingPathComponent(folderName, isDirectory: true)

        do {
            try fm.createDirectory(at: sessionFolder, withIntermediateDirectories: true)

            let destLabel: String = usedExternalForCurrentSession ? "external" : "internal"
            try await captureSession.startSession(
                folderURL: sessionFolder,
                sessionId: sessionId,
                storageDestination: destLabel,
                securityScopedExternal: securityScoped,
                deltaThreshold: captureDeltaThreshold,
                maxDepthMeters: 8.0,
                diagnostic: diagnosticInfo
            )

            let depthDir = sessionFolder.appendingPathComponent("depth", isDirectory: true)
            let rgbDir = sessionFolder.appendingPathComponent("rgb", isDirectory: true)
            let confidenceDir = sessionFolder.appendingPathComponent("confidence", isDirectory: true)
            let streamsDir = sessionFolder.appendingPathComponent("streams", isDirectory: true)

            try fm.createDirectory(at: confidenceDir, withIntermediateDirectories: true)

            let session = captureSession
            depthCaptureManager.configureSessionCapture(
                depthDirectory: depthDir,
                rgbDirectory: rgbDir,
                confidenceDirectory: confidenceDir,
                streamsDirectory: streamsDir,
                deltaThresholdMeanU16: captureDeltaThreshold,
                capturesSmoothedDepth: capturesSmoothedDepth,
                targetCaptureFPS: 30,
                captureProfile: captureProfile,
                enabledFrameSemantics: enabledSemantics,
                onSaved: nil,
                onV2Saved: { record in
                    try? await session.appendV2StreamFrame(record)
                }
            )

            let strokesURL = sessionFolder.appendingPathComponent("strokes.json")
            await handPoseManager.setStrokeOutputURL(strokesURL)
            await handPoseManager.setPaused(false)
            pendingStrokeAlignment = true

            Task { await locationCaptureManager.startCapture() }

            audioStartMonotonic = 0
            if recordAudio {
                let audioURL = sessionFolder.appendingPathComponent("audio.m4a")
                let micOK = await audioRecorder.requestPermission()
                if micOK {
                    audioStartMonotonic = await captureSession.monotonicElapsedSeconds()
                    do {
                        try audioRecorder.startRecording(to: audioURL)
                    } catch {
                        audioStartMonotonic = 0
                        warningBanner = (warningBanner ?? "") + " Audio failed to start."
                    }
                } else {
                    if audioRecorder.permissionDenied {
                        warningBanner = (warningBanner ?? "") + " Microphone denied; session has no audio."
                    }
                }
            }

            trayDetectionLocked = false
            auxiliaryFrameCounter = 0
            await handPoseManager.resetGestureState()
            handPoseManager.setTargetFrameRate(15)
            handPoseManager.setCaptureActive(true)
            isCaptureRecording = true
            isCapturePaused = false
            depthCaptureManager.setRecording(true)
        } catch {
            activeDepthDiagnosticProfile = nil
            warningBanner = "Could not start session: \(error.localizedDescription)"
            if securityScoped, let ext = externalScopedURL {
                ext.stopAccessingSecurityScopedResource()
                externalScopedURL = nil
            }
        }
    }

    private func stopActiveCaptureSession(reason: StopReason) async {
        guard isCaptureRecording else { return }
        let wasBenchmarkRunning = isBenchmarkRunning
        let wasDepthDiagnosticRunning = isDepthDiagnosticRunning

        await stopCaptureSession()

        if wasBenchmarkRunning {
            isBenchmarkRunning = false
            benchmarkSummary = "Benchmark stopped."
            if reason == .manual {
                warningBanner = "Benchmark stopped."
            }
        }

        if wasDepthDiagnosticRunning {
            isDepthDiagnosticRunning = false
            depthDiagnosticSummary = "Depth diagnostic stopped."
            if reason == .manual {
                warningBanner = "Depth diagnostic stopped."
            }
        }
    }

    private func stopCaptureSession() async {
        handPoseManager.setCaptureActive(false)
        locationCaptureManager.stopCapture()
        await depthCaptureManager.stopAndFinishRecording()
        isCaptureRecording = false
        isCapturePaused = false
        let diagnosticSnapshot = await depthCaptureManager.benchmarkSnapshot()

        let audioInfo = audioRecorder.stopRecording()
        if let info = audioInfo {
            try? await captureSession.setAudioEntry(
                .init(
                    relativePath: "audio.m4a",
                    startMonotonicElapsedSeconds: audioStartMonotonic,
                    durationSeconds: info.duration,
                    sampleRate: info.sampleRate,
                    channelCount: info.channels,
                    format: "aac"
                )
            )
        }

        if let loc = locationCaptureManager.getSessionLocation() {
            try? await captureSession.setLocation(
                latitude: loc.latitude,
                longitude: loc.longitude,
                altitude: loc.altitude
            )
        }

        if activeDepthDiagnosticProfile != nil {
            try? await captureSession.setDepthDiagnosticCounters(diagnosticSnapshot.diagnosticCounters())
        }

        let folder = try? await captureSession.stopSession()
        lastSessionFolderURL = folder
        activeDepthDiagnosticProfile = nil

        if let folder, uploadSettings.isEnabled(), let endpoint = uploadSettings.endpointURL() {
            uploadStatus = "Uploading session..."
            Task {
                do {
                    try await uploadManager.uploadSessionFolder(folder, to: endpoint)
                    await MainActor.run { self.uploadStatus = "Upload complete" }
                } catch {
                    await MainActor.run { self.uploadStatus = "Upload failed: \(error.localizedDescription)" }
                }
            }
        }

        await handPoseManager.setStrokeOutputURL(nil)
        await handPoseManager.setPaused(false)

        depthCaptureManager.configureSessionCapture(
            depthDirectory: nil as URL?,
            rgbDirectory: nil as URL?,
            confidenceDirectory: nil as URL?,
            streamsDirectory: nil as URL?,
            deltaThresholdMeanU16: depthDeltaThresholdMeanU16,
            capturesSmoothedDepth: true,
            targetCaptureFPS: 30,
            captureProfile: "standard",
            enabledFrameSemantics: ["sceneDepth", "smoothedSceneDepth"],
            onSaved: nil as (@Sendable (TimeInterval, String, String, String?, [Float]?, [Float]?) async -> Void)?,
            onV2Saved: nil as (@Sendable (V2StreamFrameRecord) async -> Void)?
        )

        capturePerformanceMode = .fullQuality
        handPoseManager.setTargetFrameRate(15)

        if let ext = externalScopedURL {
            ext.stopAccessingSecurityScopedResource()
            externalScopedURL = nil
        }
    }

    private func internalSessionsRoot() -> URL {
        let docs = fm.urls(for: .documentDirectory, in: .userDomainMask).first!
        let root = docs.appendingPathComponent("SandStoriesSessions", isDirectory: true)
        try? fm.createDirectory(at: root, withIntermediateDirectories: true)
        return root
    }

    private var fm: FileManager { FileManager.default }

    private func fallbackToInternalStorage(reason: String) {
        storageStore.setInternal()
        warningBanner = reason + " Using Internal."
        refreshDestinationLabel()
    }
}
