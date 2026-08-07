import ARKit
import Foundation

/// AR frame hook for tray boundary + object detection while capture recording is active.
@MainActor
final class SessionFramePipeline: NSObject, @preconcurrency ARSessionDelegate {
    weak var coordinator: RecordingCoordinator?
    private var isProcessing = false

    func session(_ session: ARSession, didUpdate frame: ARFrame) {
        guard let coordinator,
              coordinator.isCaptureRecording,
              !coordinator.isCapturePaused,
              !isProcessing else { return }
        isProcessing = true

        // Extract sendable values synchronously — never retain ARFrame across async boundaries.
        let timestamp = frame.timestamp
        let pixelBuffer = PixelBufferBox(frame.capturedImage)

        Task {
            await coordinator.processAuxiliaryCaptureFrame(
                arTimestamp: timestamp,
                capturedImage: pixelBuffer
            )
            self.isProcessing = false
        }
    }
}
