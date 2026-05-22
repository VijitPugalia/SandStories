import Foundation
import simd

actor StrokeRecorder {
    struct StrokePoint: Codable, Sendable {
        let timestamp: TimeInterval
        let x: Float
        let y: Float
        let z: Float

        var position: simd_float3 {
            simd_float3(x, y, z)
        }
    }

    struct Stroke: Codable, Sendable {
        let startedAt: TimeInterval
        let finishedAt: TimeInterval
        let points: [StrokePoint]
    }

    enum DetectedEvent: Sendable {
        case started(point: StrokePoint)
        case appended(point: StrokePoint)
        case none
    }

    enum MissingEvent: Sendable {
        case finished(stroke: Stroke)
        case none
    }

    // Tune these for how “hold” should behave.
    private let endStrokeAfterSeconds: TimeInterval = 0.25
    private let minPointTimeStep: TimeInterval = 0.03
    private let minPointDistanceMeters: Float = 0.004

    private var isRecording: Bool = false
    private var activePoints: [StrokePoint] = []
    private var startedAt: TimeInterval?
    private var lastDetectedAt: TimeInterval?
    private var lastPoint: simd_float3?

    private var loadedFromDisk: Bool = false
    private var storedStrokes: [Stroke] = []
    private var sessionStartAt: TimeInterval = 0
    private var sessionStrokes: [Stroke] = []
    /// When set, packaged sessions write strokes only to this file (e.g. `session_…/strokes.json`).
    private var captureOutputURL: URL?
    private let encoder: JSONEncoder = {
        let enc = JSONEncoder()
        enc.outputFormatting = [.prettyPrinted, .withoutEscapingSlashes]
        return enc
    }()

    private var effectiveStrokesURL: URL {
        if let captureOutputURL {
            return captureOutputURL
        }
        let documentsURL = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask).first!
        return documentsURL.appendingPathComponent("strokes.json")
    }

    /// Point stroke persistence at a session file, or `nil` for legacy `Documents/strokes.json`.
    func setCaptureOutputURL(_ url: URL?) {
        captureOutputURL = url
        loadedFromDisk = false
        sessionStrokes = []
    }

    func beginSession(startedAt: TimeInterval) {
        sessionStartAt = startedAt
        sessionStrokes = []
    }

    func getSessionStrokes() -> [Stroke] {
        sessionStrokes
    }

    func clearActiveStroke() {
        isRecording = false
        activePoints = []
        startedAt = nil
        lastDetectedAt = nil
        lastPoint = nil
    }

    func ingestDetected(position: simd_float3, timestamp: TimeInterval) async -> DetectedEvent {
        lastDetectedAt = timestamp

        let point = StrokePoint(timestamp: timestamp, x: position.x, y: position.y, z: position.z)

        if !isRecording {
            isRecording = true
            startedAt = timestamp
            activePoints = [point]
            lastPoint = position
            return .started(point: point)
        }

        if let lastPoint, let lastTimestamp = activePoints.last?.timestamp {
            let dt = timestamp - lastTimestamp
            let distSq = simd_distance_squared(lastPoint, position)

            guard dt >= minPointTimeStep || distSq >= (minPointDistanceMeters * minPointDistanceMeters) else {
                return .none
            }
        }

        activePoints.append(point)
        lastPoint = position
        return .appended(point: point)
    }

    func ingestMissing(timestamp: TimeInterval) async -> MissingEvent {
        guard isRecording else { return .none }
        guard let lastDetectedAt else { return .none }

        if timestamp - lastDetectedAt < endStrokeAfterSeconds {
            return .none
        }

        guard let startedAt else { return .none }
        guard !activePoints.isEmpty else {
            clearActiveStroke()
            return .none
        }

        let stroke = Stroke(startedAt: startedAt, finishedAt: timestamp, points: activePoints)
        // Reset state first to avoid re-entrancy issues if writing triggers new callbacks.
        clearActiveStroke()

        do {
            try await appendStrokeToDisk(stroke)
        } catch {
            print("StrokeRecorder append error: \(error)")
        }

        return .finished(stroke: stroke)
    }

    private func appendStrokeToDisk(_ stroke: Stroke) async throws {
        try await ensureLoaded()
        storedStrokes.append(stroke)

        if stroke.startedAt >= sessionStartAt {
            sessionStrokes.append(stroke)
        }

        let data = try encoder.encode(storedStrokes)
        try data.write(to: effectiveStrokesURL, options: [.atomic])
    }

    private func ensureLoaded() async throws {
        guard !loadedFromDisk else { return }
        loadedFromDisk = true

        let url = effectiveStrokesURL
        guard FileManager.default.fileExists(atPath: url.path) else {
            storedStrokes = []
            return
        }

        let data = try Data(contentsOf: url)
        storedStrokes = try decoder.decode([Stroke].self, from: data)
    }

    private var decoder: JSONDecoder {
        JSONDecoder()
    }
}

