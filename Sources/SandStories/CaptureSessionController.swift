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
        maxDepthMeters: Float
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
        try fm.createDirectory(at: depthDir, withIntermediateDirectories: true)
        try fm.createDirectory(at: rgbDir, withIntermediateDirectories: true)

        let meta = await MainActor.run {
            let d = UIDevice.current
            let appVersion = Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "0"
            return (model: d.model, os: d.systemVersion, appVersion: appVersion)
        }

        manifest = CaptureSessionManifest(
            schemaVersion: 1,
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
                format: "png16_grayscale_zlib",
                maxDepthMeters: maxDepthMeters,
                deltaMeanAbsThresholdU16: deltaThreshold,
                note: "16-bit PNG uses zlib compression; depth quantized 0..maxDepthMeters -> UInt16"
            ),
            depthFrames: [],
            rgbFrames: [],
            audio: nil,
            strokesFile: "strokes.json",
            trayBoundary: .init(status: "pending", cornersNormalized: nil, note: nil),
            objectDetectionsFile: "objects.jsonl",
            location: nil
        )

        let objectsURL = folderURL.appendingPathComponent("objects.jsonl")
        fm.createFile(atPath: objectsURL.path, contents: nil)
        objectsFileHandle = try FileHandle(forWritingTo: objectsURL)
        try objectsFileHandle?.seekToEnd()

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
        rgbRelativePath: String
    ) async throws {
        guard var m = manifest, sessionStartMach != 0 else { return }
        let mono = monotonicElapsedSeconds()
        depthFrameIndex += 1
        rgbFrameIndex += 1
        m.depthFrames.append(
            .init(frameIndex: depthFrameIndex, arTimestamp: arTimestamp, monotonicElapsedSeconds: mono, relativePath: depthRelativePath)
        )
        m.rgbFrames.append(
            .init(frameIndex: rgbFrameIndex, arTimestamp: arTimestamp, monotonicElapsedSeconds: mono, relativePath: rgbRelativePath)
        )
        manifest = m
        try await writeManifest()
    }

    func setAudioEntry(_ entry: CaptureSessionManifest.AudioEntry) async throws {
        guard var m = manifest else { return }
        m.audio = entry
        manifest = m
        try await writeManifest()
    }

    func setTrayBoundary(_ entry: CaptureSessionManifest.TrayBoundaryEntry) async throws {
        guard var m = manifest else { return }
        m.trayBoundary = entry
        manifest = m
        try await writeManifest()
    }

    func appendObjectLine(_ record: StoryObjectDetectionRecord) async throws {
        guard let handle = objectsFileHandle else { return }
        let data = try jsonLinesEncoder.encode(record)
        var line = data
        line.append(0x0A) // newline
        try handle.write(contentsOf: line)
    }

    func setLocation(latitude: Double, longitude: Double, altitude: Double?) async throws {
        guard var m = manifest else { return }
        m.location = .init(latitude: latitude, longitude: longitude, altitude: altitude)
        manifest = m
        try await writeManifest()
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
        try await writeManifest()
        sessionStartMach = 0
        return folder
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
        sessionFolderURL = nil
        sessionId = nil
        manifest = nil
        sessionStartMach = 0
        depthFrameIndex = 0
        rgbFrameIndex = 0
    }
}
