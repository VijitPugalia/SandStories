import ARKit
import Foundation

/// AR frame hook for tray boundary + object detection while capture recording is active.
final class SessionFramePipeline: NSObject, ARSessionDelegate {
    weak var coordinator: RecordingCoordinator?

    func session(_ session: ARSession, didUpdate frame: ARFrame) {
        let f = frame
        Task { @MainActor [weak coordinator] in
            await coordinator?.processAuxiliaryCaptureFrame(f)
        }
    }
}
