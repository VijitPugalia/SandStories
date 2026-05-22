import CoreVideo
import Foundation
import Vision

/// Pluggable storytelling-object detector (e.g. swap in YOLO-World later).
protocol StoryObjectDetecting: Sendable {
    func detect(
        pixelBuffer: CVPixelBuffer,
        orientation: CGImagePropertyOrientation,
        arTimestamp: TimeInterval,
        monotonicElapsedSeconds: Double
    ) async -> [StoryObjectDetectionRecord]
}

/// Default: no detections; persists empty pipeline and manifest references.
struct StubStoryObjectDetector: StoryObjectDetecting {
    func detect(
        pixelBuffer: CVPixelBuffer,
        orientation: CGImagePropertyOrientation,
        arTimestamp: TimeInterval,
        monotonicElapsedSeconds: Double
    ) async -> [StoryObjectDetectionRecord] {
        _ = pixelBuffer
        _ = orientation
        _ = arTimestamp
        _ = monotonicElapsedSeconds
        return []
    }
}
