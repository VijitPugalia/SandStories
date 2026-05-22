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

    private let objectDetector: any StoryObjectDetecting = StubStoryObjectDetector()

    /// Mean absolute delta on 32×32 downsampled UInt16 depth; skip save when below this (configurable).
    var depthDeltaThresholdMeanU16: Float = 400

    @Published private(set) var isCaptureRecording = false
    @Published var destinationLabel: String = "Saving to: Internal"
    @Published var warningBanner: String?
    @Published var showingFolderPicker = false
    @Published private(set) var lastSessionFolderURL: URL?

    private var externalScopedURL: URL?
    private var trayDetectionLocked = false
    private var auxiliaryFrameCounter = 0
    private var pendingStrokeAlignment = false
    private var audioStartMonotonic: Double = 0
    private var usedExternalForCurrentSession = false

    init() {
        framePipeline.coordinator = self
        refreshDestinationLabel()
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
    func toggleRecording(locationCaptureManager: LocationCaptureManager) async {
        if isCaptureRecording {
            await stopCaptureSession(locationCaptureManager: locationCaptureManager)
        } else {
            await startCaptureSession(locationCaptureManager: locationCaptureManager)
        }
    }

    func processAuxiliaryCaptureFrame(_ frame: ARFrame) async {
        guard isCaptureRecording else { return }
        await captureSession.noteFirstARFrameIfNeeded(frame.timestamp)
        auxiliaryFrameCounter += 1

        if pendingStrokeAlignment {
            pendingStrokeAlignment = false
            await handPoseManager.alignStrokeSessionStart(arTimestamp: frame.timestamp)
        }

        if auxiliaryFrameCounter % 45 == 0, !trayDetectionLocked {
            if let tray = TrayBoundaryDetector.detectCorners(
                pixelBuffer: frame.capturedImage,
                orientation: CGImagePropertyOrientation.right
            ) {
                trayDetectionLocked = true
                try? await captureSession.setTrayBoundary(
                    .init(status: "detected", cornersNormalized: tray.corners, note: "saturation corner heuristic; Vision-style normalized coords")
                )
            }
        }

        if auxiliaryFrameCounter % 28 == 0 {
            let mono = await captureSession.monotonicElapsedSeconds()
            let recs = await objectDetector.detect(
                pixelBuffer: frame.capturedImage,
                orientation: .right,
                arTimestamp: frame.timestamp,
                monotonicElapsedSeconds: mono
            )
            for r in recs {
                try? await captureSession.appendObjectLine(r)
            }
        }
    }

    // MARK: - Private

    private func startCaptureSession(locationCaptureManager: LocationCaptureManager) async {
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
            pendingStrokeAlignment = true

            audioStartMonotonic = 0
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

            trayDetectionLocked = false
            auxiliaryFrameCounter = 0
            isCaptureRecording = true
            depthCaptureManager.setRecording(true)
        } catch {
            warningBanner = "Could not start session: \(error.localizedDescription)"
            if securityScoped, let ext = externalScopedURL {
                ext.stopAccessingSecurityScopedResource()
                externalScopedURL = nil
            }
        }
    }

    private func stopCaptureSession(locationCaptureManager: LocationCaptureManager) async {
        depthCaptureManager.setRecording(false)
        isCaptureRecording = false

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
