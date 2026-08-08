import Darwin
import Foundation
import UIKit

/// Owns one recording session folder, `manifest.json`, and `objects.jsonl` appends.
actor CaptureSessionController {
    private(set) var sessionFolderURL: URL?
    private(set) var sessionId: UUID?
    private var manifest: CaptureSessionManifest?
    /// Mach absolute time at session start (monotonic, shared time base).
    private var sessionStartMach: UInt64 = 0
    private var machTimebase: mach_timebase_info_data_t = .init(numer: 0, denom: 0)
    private var wallStart: TimeInterval = 0
    private var depthFrameIndex: Int = 0
    private var rgbFrameIndex: Int = 0
    private var firstARTimestamp: TimeInterval?
    private let encoder: JSONEncoder = {
        let e = JSONEncoder()
        e.outputFormatting = [.prettyPrinted, .withoutEscapingSlashes]
        return e
    }()

    /// One JSON object per line (no pretty printing).
    private let jsonLinesEncoder: JSONEncoder = {
        let e = JSONEncoder()
        e.outputFormatting = [.withoutEscapingSlashes]
        return e
    }()

    private var objectsFileHandle: FileHandle?
    private var boundarySamplesFileHandle: FileHandle?
    private var v2FramesFileHandle: FileHandle?
    private var framesSinceLastManifestWrite: Int = 0
    private let manifestWriteBatchSize: Int = 5

    /// Elapsed seconds on monotonic session clock (shared time base).
    func monotonicElapsedSeconds() -> Double {
        guard sessionStartMach != 0 else { return 0 }
        let now = mach_absolute_time()
        let delta = now &- sessionStartMach
        let nanos = Double(delta) * Double(machTimebase.numer) / Double(machTimebase.denom)
        return nanos / 1e9
    }

    func startSession(
        folderURL: URL,
        sessionId: UUID,
        storageDestination: String,
        securityScopedExternal: Bool,
        deltaThreshold: Float,
        maxDepthMeters: Float,
        diagnostic: CaptureSessionManifest.DepthDiagnosticInfo? = nil
    ) async throws {
        self.sessionFolderURL = folderURL
        self.sessionId = sessionId
        mach_timebase_info(&machTimebase)
        self.sessionStartMach = mach_absolute_time()
        self.wallStart = Date().timeIntervalSince1970
        self.depthFrameIndex = 0
        self.rgbFrameIndex = 0
        self.firstARTimestamp = nil

        let fm = FileManager.default
        let depthDir = folderURL.appendingPathComponent("depth", isDirectory: true)
        let rgbDir = folderURL.appendingPathComponent("rgb", isDirectory: true)
        let streamsDir = folderURL.appendingPathComponent("streams", isDirectory: true)
        try fm.createDirectory(at: depthDir, withIntermediateDirectories: true)
        try fm.createDirectory(at: rgbDir, withIntermediateDirectories: true)
        try fm.createDirectory(at: streamsDir, withIntermediateDirectories: true)

        let meta = await MainActor.run {
            let d = UIDevice.current
            let appVersion = Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "0"
            return (model: d.model, os: d.systemVersion, appVersion: appVersion)
        }

        manifest = CaptureSessionManifest(
            schemaVersion: 1,
            captureFormat: "v2_streams",
            sessionId: sessionId.uuidString,
            deviceModel: meta.model,
            osVersion: meta.os,
            appVersion: meta.appVersion,
            wallClockStartUnix: wallStart,
            wallClockEndUnix: nil,
            monotonicSessionStart: .init(description: "ContinuousClock session origin"),
            monotonicSessionEndElapsedSeconds: nil,
            arKitTimeReference: .init(firstFrameTimestamp: nil, note: "ar_timestamp matches ARFrame.timestamp seconds"),
            storage: .init(
                destination: storageDestination,
                sessionFolderRelative: folderURL.lastPathComponent,
                securityScopedExternal: securityScopedExternal
            ),
            depthEncoding: .init(
                format: "v2_streams_float32",
                maxDepthMeters: maxDepthMeters,
                deltaMeanAbsThresholdU16: deltaThreshold,
                note: "streams/depth.f32 stores the selected primary ARKit depth source as contiguous little-endian Float32 meters; raw sceneDepth is preferred and smoothedSceneDepth is the fallback"
            ),
            depthFrames: [],
            rgbFrames: [],
            audio: nil,
            strokesFile: "strokes.json",
            trayBoundary: .init(status: "pending", cornersNormalized: nil, note: nil),
            objectDetectionsFile: "objects.jsonl",
            v2Streams: .init(
                formatVersion: 2,
                frameMetadataFile: "v2_frames.jsonl",
                rgbVideoPath: "streams/rgb.mp4",
                rgbVideoCodec: "h264_mp4",
                depthStreamPath: "streams/depth.f32",
                depthFormat: "float32_little_endian_meters_contiguous",
                smoothedDepthStreamPath: "streams/smoothed_depth.f32",
                confidenceStreamPath: "streams/confidence.bin",
                note: "v2_frames.jsonl selectedDepthSource is authoritative: depth.f32 stores raw sceneDepth when available or smoothedSceneDepth as fallback; smoothed_depth.f32 is populated only when raw is primary and a smoothed sidecar is available"
            ),
            objectDetectionProvenance: "postprocessed_yolo_world_v1",
            boundarySamplesFile: "boundary_samples.jsonl",
            location: nil,
            segments: nil,
            diagnostic: diagnostic
        )

        let objectsURL = folderURL.appendingPathComponent("objects.jsonl")
        fm.createFile(atPath: objectsURL.path, contents: nil)
        objectsFileHandle = try FileHandle(forWritingTo: objectsURL)
        try objectsFileHandle?.seekToEnd()

        let boundaryURL = folderURL.appendingPathComponent("boundary_samples.jsonl")
        fm.createFile(atPath: boundaryURL.path, contents: nil)
        boundarySamplesFileHandle = try FileHandle(forWritingTo: boundaryURL)
        try boundarySamplesFileHandle?.seekToEnd()

        let v2FramesURL = folderURL.appendingPathComponent("v2_frames.jsonl")
        fm.createFile(atPath: v2FramesURL.path, contents: nil)
        v2FramesFileHandle = try FileHandle(forWritingTo: v2FramesURL)
        try v2FramesFileHandle?.seekToEnd()

        try await writeManifest()
    }

    func noteFirstARFrameIfNeeded(_ arTimestamp: TimeInterval) async {
        guard var m = manifest else { return }
        if m.arKitTimeReference?.firstFrameTimestamp == nil {
            m.arKitTimeReference = .init(firstFrameTimestamp: arTimestamp, note: m.arKitTimeReference?.note ?? "")
            manifest = m
        }
    }

    func appendDepthAndRGB(
        arTimestamp: TimeInterval,
        depthRelativePath: String,
        rgbRelativePath: String,
        confidenceRelativePath: String?,
        cameraIntrinsics: [Float]?,
        cameraTransform: [Float]?
    ) async throws {
        guard var m = manifest, sessionStartMach != 0 else { return }
        let mono = monotonicElapsedSeconds()
        depthFrameIndex += 1
        rgbFrameIndex += 1
        m.depthFrames.append(
            .init(
                frameIndex: depthFrameIndex,
                arTimestamp: arTimestamp,
                monotonicElapsedSeconds: mono,
                relativePath: depthRelativePath,
                confidencePath: confidenceRelativePath,
                cameraIntrinsics: cameraIntrinsics,
                cameraTransform: cameraTransform
            )
        )
        m.rgbFrames.append(
            .init(frameIndex: rgbFrameIndex, arTimestamp: arTimestamp, monotonicElapsedSeconds: mono, relativePath: rgbRelativePath)
        )
        manifest = m
        try await scheduleManifestWrite()
    }

    func setAudioEntry(_ entry: CaptureSessionManifest.AudioEntry) async throws {
        guard var m = manifest else { return }
        m.audio = entry
        manifest = m
        try await flushManifest()
    }

    func setTrayBoundary(_ entry: CaptureSessionManifest.TrayBoundaryEntry) async throws {
        guard var m = manifest else { return }
        m.trayBoundary = entry
        manifest = m
        try await flushManifest()
    }

    func appendObjectLine(_ record: StoryObjectDetectionRecord) async throws {
        guard let handle = objectsFileHandle else { return }
        let data = try jsonLinesEncoder.encode(record)
        var line = data
        line.append(0x0A) // newline
        try handle.write(contentsOf: line)
    }

    func appendBoundarySample(_ sample: TrayBoundarySample) async throws {
        guard let handle = boundarySamplesFileHandle else { return }
        let data = try jsonLinesEncoder.encode(sample)
        var line = data
        line.append(0x0A) // newline
        try handle.write(contentsOf: line)
    }

    func appendV2StreamFrame(_ record: V2StreamFrameRecord) async throws {
        guard let handle = v2FramesFileHandle else { return }
        var enriched = record
        enriched.monotonicElapsedSeconds = monotonicElapsedSeconds()
        let data = try jsonLinesEncoder.encode(enriched)
        var line = data
        line.append(0x0A) // newline
        try handle.write(contentsOf: line)
    }

    func setLocation(latitude: Double, longitude: Double, altitude: Double?) async throws {
        guard var m = manifest else { return }
        m.location = .init(latitude: latitude, longitude: longitude, altitude: altitude)
        manifest = m
        try await flushManifest()
    }

    func markSegment() async throws {
        guard var m = manifest else { return }
        let mono = monotonicElapsedSeconds()
        let unix = Date().timeIntervalSince1970
        var currentSegments = m.segments ?? []
        currentSegments.append(.init(monotonicElapsedSeconds: mono, timestampUnix: unix))
        m.segments = currentSegments
        manifest = m
        try await flushManifest()
    }

    func setDepthDiagnosticCounters(_ counters: CaptureSessionManifest.DepthDiagnosticCounters) async throws {
        guard var m = manifest, var diagnostic = m.diagnostic else { return }
        diagnostic.counters = counters
        m.diagnostic = diagnostic
        manifest = m
        try await flushManifest()
    }

    func stopSession() async throws -> URL? {
        guard let folder = sessionFolderURL else { return nil }
        let monoEnd = monotonicElapsedSeconds()
        if var m = manifest {
            m.wallClockEndUnix = Date().timeIntervalSince1970
            m.monotonicSessionEndElapsedSeconds = monoEnd
            manifest = m
        }
        try objectsFileHandle?.close()
        objectsFileHandle = nil
        try boundarySamplesFileHandle?.close()
        boundarySamplesFileHandle = nil
        try v2FramesFileHandle?.close()
        v2FramesFileHandle = nil
        try await flushManifest()
        sessionStartMach = 0
        return folder
    }

    private func scheduleManifestWrite() async throws {
        framesSinceLastManifestWrite += 1
        if framesSinceLastManifestWrite >= manifestWriteBatchSize {
            try await flushManifest()
        }
    }

    private func flushManifest() async throws {
        framesSinceLastManifestWrite = 0
        try await writeManifest()
    }

    private func writeManifest() async throws {
        guard let folder = sessionFolderURL, let m = manifest else { return }
        let url = folder.appendingPathComponent("manifest.json")
        let data = try encoder.encode(m)
        try data.write(to: url, options: [.atomic])
    }

    func reset() async {
        try? objectsFileHandle?.close()
        objectsFileHandle = nil
        try? boundarySamplesFileHandle?.close()
        boundarySamplesFileHandle = nil
        try? v2FramesFileHandle?.close()
        v2FramesFileHandle = nil
        sessionFolderURL = nil
        sessionId = nil
        manifest = nil
        sessionStartMach = 0
        depthFrameIndex = 0
        rgbFrameIndex = 0
        framesSinceLastManifestWrite = 0
    }
}
