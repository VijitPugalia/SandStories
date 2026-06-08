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

    private let objectDetector: any StoryObjectDetecting = StubStoryObjectDetector()

    /// Mean absolute delta on 32×32 downsampled UInt16 depth; skip save when below this (configurable).
    var depthDeltaThresholdMeanU16: Float = 400

    @Published private(set) var isCaptureRecording = false
    @Published private(set) var isCapturePaused = false
    @Published var destinationLabel: String = "Saving to: Internal"
    @Published var warningBanner: String?
    @Published var showingFolderPicker = false
    @Published private(set) var lastSessionFolderURL: URL?
    @Published private(set) var isBenchmarkRunning = false
    @Published private(set) var benchmarkSummary: String?

    private var externalScopedURL: URL?
    private var trayDetectionLocked = false
    private var auxiliaryFrameCounter = 0
    private var pendingStrokeAlignment = false
    private var audioStartMonotonic: Double = 0
    private var usedExternalForCurrentSession = false

    init() {
        framePipeline.coordinator = self
        refreshDestinationLabel()
        
        handPoseManager.onGestureCommand = { [weak self] command in
            guard let self else { return }
            Task {
                switch command {
                case .start:
                    if !self.isCaptureRecording {
                        await self.startCaptureSession(recordAudio: true)
                    }
                case .stop:
                    if self.isCaptureRecording {
                        await self.stopCaptureSession()
                    }
                case .pause:
                    await self.pauseCaptureSession()
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
        guard !isBenchmarkRunning else { return }
        if isCaptureRecording {
            await stopCaptureSession()
        } else {
            await startCaptureSession()
        }
    }

    func runDepthBenchmark() async {
        guard !isCaptureRecording, !isBenchmarkRunning else { return }

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

        await stopCaptureSession()

        let elapsed = Date().timeIntervalSince(start)
        let snapshot = await depthCaptureManager.benchmarkSnapshot()
        let summary = snapshot.summary(elapsedSeconds: elapsed)
        benchmarkSummary = summary
        warningBanner = "Benchmark complete. \(summary)"
        print(summary)
        isBenchmarkRunning = false
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

    private func startCaptureSession(recordAudio: Bool = true) async {
        warningBanner = nil
        let sessionId = UUID()
        let fm = FileManager.default

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
                deltaThreshold: depthDeltaThresholdMeanU16,
                maxDepthMeters: 8.0
            )

            let depthDir = sessionFolder.appendingPathComponent("depth", isDirectory: true)
            let rgbDir = sessionFolder.appendingPathComponent("rgb", isDirectory: true)

            let session = captureSession
            depthCaptureManager.configureSessionCapture(
                depthDirectory: depthDir,
                rgbDirectory: rgbDir,
                deltaThresholdMeanU16: depthDeltaThresholdMeanU16,
                onSaved: { ts, dPath, rPath in
                    try? await session.appendDepthAndRGB(
                        arTimestamp: ts,
                        depthRelativePath: dPath,
                        rgbRelativePath: rPath
                    )
                }
            )

            let strokesURL = sessionFolder.appendingPathComponent("strokes.json")
            await handPoseManager.setStrokeOutputURL(strokesURL)
            await handPoseManager.setPaused(false)
            pendingStrokeAlignment = true

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
            isCaptureRecording = true
            isCapturePaused = false
            depthCaptureManager.setRecording(true)
        } catch {
            warningBanner = "Could not start session: \(error.localizedDescription)"
            if securityScoped, let ext = externalScopedURL {
                ext.stopAccessingSecurityScopedResource()
                externalScopedURL = nil
            }
        }
    }

    private func stopCaptureSession() async {
        depthCaptureManager.setRecording(false)
        isCaptureRecording = false
        isCapturePaused = false

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

        let folder = try? await captureSession.stopSession()
        lastSessionFolderURL = folder

        await handPoseManager.setStrokeOutputURL(nil)
        await handPoseManager.setPaused(false)

        depthCaptureManager.configureSessionCapture(
            depthDirectory: nil as URL?,
            rgbDirectory: nil as URL?,
            deltaThresholdMeanU16: depthDeltaThresholdMeanU16,
            onSaved: nil as (@Sendable (TimeInterval, String, String) async -> Void)?
        )

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
