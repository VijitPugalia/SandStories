import Foundation

/// Canonical JSON manifest for a sand-storytelling capture session (replay tools read this).
struct CaptureSessionManifest: Codable, Sendable {
    var schemaVersion: Int
    var sessionId: String
    var deviceModel: String
    var osVersion: String
    var appVersion: String

    /// Wall-clock session bounds
    var wallClockStartUnix: TimeInterval
    var wallClockEndUnix: TimeInterval?

    /// Monotonic session clock: seconds elapsed since `monotonicSessionStart` (ContinuousClock), shared by all modalities.
    var monotonicSessionStart: MonotonicAnchor
    var monotonicSessionEndElapsedSeconds: Double?

    /// Optional ARKit time base (seconds) for frames that use `ARFrame.timestamp`
    var arKitTimeReference: ARKitTimeReference?

    var storage: StorageInfo
    var depthEncoding: DepthEncodingInfo
    var depthFrames: [DepthFrameEntry]
    var rgbFrames: [RGBFrameEntry]
    var audio: AudioEntry?
    var strokesFile: String
    var trayBoundary: TrayBoundaryEntry
    var objectDetectionsFile: String
    var objectDetectionProvenance: String?
    var boundarySamplesFile: String
    var location: SessionLocationEntry?
    var segments: [SegmentMarkEntry]?

    struct MonotonicAnchor: Codable, Sendable {
        /// Nanoseconds from an arbitrary monotonic origin at session start (for debugging).
        var description: String
    }

    struct ARKitTimeReference: Codable, Sendable {
        var firstFrameTimestamp: TimeInterval?
        var note: String
    }

    struct StorageInfo: Codable, Sendable {
        var destination: String // "internal" | "external"
        var sessionFolderRelative: String
        var securityScopedExternal: Bool
    }

    struct DepthEncodingInfo: Codable, Sendable {
        var format: String // "png16_grayscale_zlib"
        var maxDepthMeters: Float
        var deltaMeanAbsThresholdU16: Float
        var note: String
    }

    struct DepthFrameEntry: Codable, Sendable {
        var frameIndex: Int
        var arTimestamp: TimeInterval
        var monotonicElapsedSeconds: Double
        var relativePath: String
        var confidencePath: String?
        var cameraIntrinsics: [Float]? // 3x3 column-major
        var cameraTransform: [Float]?  // 4x4 column-major
    }

    struct RGBFrameEntry: Codable, Sendable {
        var frameIndex: Int
        var arTimestamp: TimeInterval
        var monotonicElapsedSeconds: Double
        var relativePath: String
    }

    struct AudioEntry: Codable, Sendable {
        var relativePath: String
        var startMonotonicElapsedSeconds: Double
        var durationSeconds: Double
        var sampleRate: Double
        var channelCount: Int
        var format: String
    }

    struct TrayBoundaryEntry: Codable, Sendable {
        var status: String
        var cornersNormalized: [[Double]]?
        var note: String?
    }

    struct SessionLocationEntry: Codable, Sendable {
        var latitude: Double
        var longitude: Double
        var altitude: Double?
    }

    struct SegmentMarkEntry: Codable, Sendable {
        var monotonicElapsedSeconds: Double
        var timestampUnix: TimeInterval
    }
}

/// One line in `objects.jsonl` (append-friendly).
struct StoryObjectDetectionRecord: Codable, Sendable {
    var arTimestamp: TimeInterval
    var monotonicElapsedSeconds: Double
    var label: String
    var confidence: Float
    /// Normalized image coordinates [0,1]: x, y, width, height (origin top-left of Vision space mapped to image).
    var boundingBoxNormalized: [Double]
}

/// One line in `boundary_samples.jsonl` (append-friendly).
struct TrayBoundarySample: Codable, Sendable {
    var arTimestamp: TimeInterval
    var monotonicElapsedSeconds: Double
    var confidence: Double
    var cornersNormalized: [[Double]]?
}
