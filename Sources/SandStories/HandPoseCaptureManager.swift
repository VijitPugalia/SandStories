import ARKit
import CoreVideo
import Foundation
import RealityKit
import Vision

// Serializes Vision hand pose requests so we never build up a backlog.
actor HandPoseVisionProcessor {
    private let request = VNDetectHumanHandPoseRequest()
    private var isProcessing = false

    init() {
        request.maximumHandCount = 1
        // The default revision is fine for iOS 17+, but explicitly setting makes intent clear.
        if #available(iOS 14.0, *) {
            // No-op: revision handled by VNDetectHumanHandPoseRequest internally across iOS versions.
        }
    }

    enum FingertipDetection: Sendable {
        case detected(CGPoint)
        case notDetected
        case busy
    }

    func detectIndexFingerTip(
        pixelBufferBox: PixelBufferBox,
        orientation: CGImagePropertyOrientation
    ) async -> FingertipDetection {
        guard !isProcessing else { return .busy }
        isProcessing = true
        defer { isProcessing = false }

        let handler = VNImageRequestHandler(cvPixelBuffer: pixelBufferBox.pixelBuffer, orientation: orientation)
        do {
            try handler.perform([request])
        } catch {
            print("HandPoseVisionProcessor perform error: \(error)")
            return .notDetected
        }

        let observations = request.results ?? []

        var bestPoint: CGPoint?
        var bestConfidence: Float = 0

        for obs in observations {
            guard let tip = try? obs.recognizedPoint(.indexTip) else { continue }
            // Some observations may return a point with low confidence.
            if tip.confidence > bestConfidence {
                bestConfidence = tip.confidence
                bestPoint = tip.location
            }
        }

        // A small confidence threshold helps reduce jitter.
        if let bestPoint, bestConfidence >= 0.3 {
            return .detected(bestPoint)
        }
        return .notDetected
    }
}

final class HandPoseSceneRenderer: @unchecked Sendable {
    private weak var arView: ARView?
    private var fingertipAnchor: AnchorEntity?
    private var sphereEntity: ModelEntity?
    private var viewportSize: CGSize = .zero

    // Stroke visualization
    private var strokeAnchors: [AnchorEntity] = []
    private var currentStrokeAnchor: AnchorEntity?

    @MainActor
    func setARView(_ arView: ARView) {
        self.arView = arView
        self.viewportSize = arView.bounds.size
    }

    func currentViewportSize() -> CGSize {
        viewportSize
    }

    /// Raycasts the screen point into the AR world using RealityKit's ARView.
    /// Returns a sendable world transform (not the raw raycast results array).
    func raycastWorldTransform(from screenPoint: CGPoint) async -> simd_float4x4? {
        await MainActor.run { [weak self] in
            guard let self, let arView else { return nil }
            let results = arView.raycast(
                from: screenPoint,
                allowing: .estimatedPlane,
                alignment: .any
            )
            return results.first?.worldTransform
        }
    }

    /// Updates/creates the fingertip sphere using an ARKit world transform.
    func renderFingertip(worldTransform: simd_float4x4) async {
        await MainActor.run { [weak self] in
            guard let self else { return }
            guard let arView else { return }

            let transform = Transform(matrix: worldTransform)

            if let fingertipAnchor {
                fingertipAnchor.transform = transform
                return
            }

            let anchor = AnchorEntity(world: worldTransform)

            if sphereEntity == nil {
                let mesh = MeshResource.generateSphere(radius: 0.01)
                let material = SimpleMaterial(color: .yellow, roughness: 0.35, isMetallic: false)
                sphereEntity = ModelEntity(mesh: mesh, materials: [material])
            }
            if let sphereEntity {
                anchor.addChild(sphereEntity)
            }

            arView.scene.addAnchor(anchor)
            fingertipAnchor = anchor
        }
    }

    func startStroke() async {
        await MainActor.run { [weak self] in
            guard let self else { return }
            guard let arView else { return }
            let anchor = AnchorEntity(world: matrix_identity_float4x4)
            arView.scene.addAnchor(anchor)
            strokeAnchors.append(anchor)
            currentStrokeAnchor = anchor
        }
    }

    func appendStrokePoint(_ position: simd_float3) async {
        await MainActor.run { [weak self] in
            guard let self else { return }
            guard let currentStrokeAnchor else { return }

            // Small sphere at each recorded point.
            let mesh = MeshResource.generateSphere(radius: 0.006)
            let material = SimpleMaterial(color: .cyan, roughness: 0.25, isMetallic: false)
            let sphere = ModelEntity(mesh: mesh, materials: [material])

            sphere.transform.translation = position
            currentStrokeAnchor.addChild(sphere)
        }
    }

    func endStroke() async {
        await MainActor.run { [weak self] in
            self?.currentStrokeAnchor = nil
        }
    }

    func clearStrokes() async {
        await MainActor.run { [weak self] in
            guard let self else { return }
            guard let arView else { return }

            for anchor in strokeAnchors {
                arView.scene.removeAnchor(anchor)
            }
            strokeAnchors.removeAll()
            currentStrokeAnchor = nil
        }
    }
}

final class HandPoseCaptureManager: NSObject, ARSessionDelegate {
    private let processor = HandPoseVisionProcessor()
    private let renderer = HandPoseSceneRenderer()
    private let strokeRecorder = StrokeRecorder()

    @MainActor
    func clearStrokes() async {
        await renderer.clearStrokes()
        await strokeRecorder.clearActiveStroke()
    }

    /// Packaged sessions: write strokes to `session_…/strokes.json`. Pass `nil` for legacy Documents file.
    @MainActor
    func setStrokeOutputURL(_ url: URL?) async {
        await strokeRecorder.setCaptureOutputURL(url)
    }

    /// Align stroke timestamps with ARKit time base when recording starts (first AR frame).
    @MainActor
    func alignStrokeSessionStart(arTimestamp: TimeInterval) async {
        await strokeRecorder.beginSession(startedAt: arTimestamp)
    }

    @MainActor
    func setARView(_ arView: ARView) {
        renderer.setARView(arView)
    }

    @MainActor
    func getSessionStrokes() async -> [StrokeRecorder.Stroke] {
        await strokeRecorder.getSessionStrokes()
    }

    func session(_ session: ARSession, didUpdate frame: ARFrame) {
        // Captured images always exist when the session is running.
        let pixelBuffer = frame.capturedImage
        let orientation: CGImagePropertyOrientation = .right

        let pixelBufferBox = PixelBufferBox(pixelBuffer)
        let processor = self.processor
        let renderer = self.renderer
        let strokeRecorder = self.strokeRecorder
        let viewportSize = renderer.currentViewportSize()

        Task(priority: .userInitiated) { [processor, renderer, strokeRecorder, viewportSize, frameTimestamp = frame.timestamp] in
            let detection = await processor.detectIndexFingerTip(
                pixelBufferBox: pixelBufferBox,
                orientation: orientation
            )

            switch detection {
            case .busy:
                return

            case .notDetected:
                let missingEvent = await strokeRecorder.ingestMissing(timestamp: frameTimestamp)
                if case .finished = missingEvent {
                    await renderer.endStroke()
                }
                return

            case .detected(let fingertip):
                // Vision normalized points have origin at bottom-left; convert to UIKit coords.
                let screenPoint = CGPoint(
                    x: fingertip.x * viewportSize.width,
                    y: (1 - fingertip.y) * viewportSize.height
                )

                guard let worldTransform = await renderer.raycastWorldTransform(from: screenPoint) else {
                    let missingEvent = await strokeRecorder.ingestMissing(timestamp: frameTimestamp)
                    if case .finished = missingEvent {
                        await renderer.endStroke()
                    }
                    return
                }

                await renderer.renderFingertip(worldTransform: worldTransform)

                let worldPosition = simd_float3(
                    worldTransform.columns.3.x,
                    worldTransform.columns.3.y,
                    worldTransform.columns.3.z
                )

                let detectedEvent = await strokeRecorder.ingestDetected(position: worldPosition, timestamp: frameTimestamp)
                switch detectedEvent {
                case .started(let point):
                    await renderer.startStroke()
                    await renderer.appendStrokePoint(point.position)
                case .appended(let point):
                    await renderer.appendStrokePoint(point.position)
                case .none:
                    break
                }
            }
        }
    }
}

