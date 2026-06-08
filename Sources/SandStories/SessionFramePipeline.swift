import ARKit
import Foundation

/// AR frame hook for tray boundary + object detection while capture recording is active.
final class SessionFramePipeline: NSObject, ARSessionDelegate {
    weak var coordinator: RecordingCoordinator?
    private let processingQueue = DispatchQueue(label: "session.frame.pipeline")
    private var isProcessing = false

    func session(_ session: ARSession, didUpdate frame: ARFrame) {
        // Extract sendable values synchronously — never retain ARFrame across async boundaries.
        let timestamp = frame.timestamp
        let pixelBuffer = PixelBufferBox(frame.capturedImage)

        processingQueue.async { [weak self] in
            guard let self else { return }
            guard !isProcessing else { return }
            isProcessing = true

            Task { @MainActor [weak coordinator, timestamp, pixelBuffer] in
                await coordinator?.processAuxiliaryCaptureFrame(
                    arTimestamp: timestamp,
                    capturedImage: pixelBuffer
                )
                processingQueue.async { [weak self] in
                    self?.isProcessing = false
                }
            }
        }
    }
}
