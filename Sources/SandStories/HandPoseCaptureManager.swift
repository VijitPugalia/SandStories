import ARKit
import CoreVideo
import Foundation
import GestureRecognition
import ImageIO
import RealityKit
import UIKit
import Vision

// Serializes Vision hand pose requests so we never build up a backlog.
actor HandPoseVisionProcessor {
    private let request = VNDetectHumanHandPoseRequest()
    private var gestureStateMachine = GestureRecognitionStateMachine()

    init() {
        request.maximumHandCount = 1
    }

    /// Reset all gesture-recognition state so no stale commands fire.
    func reset() {
        gestureStateMachine.reset(at: ProcessInfo.processInfo.systemUptime)
    }

    struct DetectionResult: Sendable {
        let fingertip: CGPoint?
        let command: UIGestureCommand?
    }

    func processFrameForFingertipAndGestures(
        pixelBufferBox: PixelBufferBox,
        orientation: CGImagePropertyOrientation,
        timestamp: TimeInterval,
        pauseEnabled: Bool,
        stopEnabled: Bool,
        markEnabled: Bool
    ) async -> DetectionResult {
        let settings = GestureRecognitionSettings(
            pauseEnabled: pauseEnabled,
            stopEnabled: stopEnabled,
            markEnabled: markEnabled
        )
        let handler = VNImageRequestHandler(
            cvPixelBuffer: pixelBufferBox.pixelBuffer,
            orientation: orientation
        )

        do {
            try handler.perform([request])
        } catch {
            print("HandPoseVisionProcessor perform error: \(error)")
            let command = gestureStateMachine.process(
                emptyFrame(timestamp: timestamp),
                settings: settings
            )
            return DetectionResult(fingertip: nil, command: command)
        }

        guard let observation = request.results?.first else {
            let command = gestureStateMachine.process(
                emptyFrame(timestamp: timestamp),
                settings: settings
            )
            return DetectionResult(fingertip: nil, command: command)
        }

        let wrist = recognizedLocation(.wrist, in: observation)
        let thumbTip = recognizedLocation(.thumbTip, in: observation)
        let indexTip = recognizedLocation(.indexTip, in: observation)
        let indexMCP = recognizedLocation(.indexMCP, in: observation)
        let middleTip = recognizedLocation(.middleTip, in: observation)
        let middleMCP = recognizedLocation(.middleMCP, in: observation)
        let ringTip = recognizedLocation(.ringTip, in: observation)
        let ringMCP = recognizedLocation(.ringMCP, in: observation)
        let littleTip = recognizedLocation(.littleTip, in: observation)
        let littleMCP = recognizedLocation(.littleMCP, in: observation)

        let isOpenPalm = HandPoseGestureClassifier.isOpenPalm(
            wrist: gesturePoint(wrist),
            fingers: [
                FingerGestureObservation(tip: gesturePoint(indexTip), base: gesturePoint(indexMCP)),
                FingerGestureObservation(tip: gesturePoint(middleTip), base: gesturePoint(middleMCP)),
                FingerGestureObservation(tip: gesturePoint(ringTip), base: gesturePoint(ringMCP)),
                FingerGestureObservation(tip: gesturePoint(littleTip), base: gesturePoint(littleMCP)),
            ]
        )

        let pinchDistance: Double?
        if let indexTip, let thumbTip {
            pinchDistance = Double(distance(indexTip, thumbTip))
        } else {
            pinchDistance = nil
        }

        let frame = GestureRecognitionFrame(
            timestamp: timestamp,
            isOpenPalm: isOpenPalm,
            wristX: wrist.map { Double($0.x) },
            wristY: wrist.map { Double($0.y) },
            pinchDistance: pinchDistance
        )
        let command = gestureStateMachine.process(frame, settings: settings)
        return DetectionResult(fingertip: indexTip, command: command)
    }

    private func emptyFrame(timestamp: TimeInterval) -> GestureRecognitionFrame {
        GestureRecognitionFrame(
            timestamp: timestamp,
            isOpenPalm: nil,
            wristX: nil,
            wristY: nil,
            pinchDistance: nil
        )
    }

    private func recognizedLocation(
        _ joint: VNHumanHandPoseObservation.JointName,
        in observation: VNHumanHandPoseObservation
    ) -> CGPoint? {
        guard let point = try? observation.recognizedPoint(joint),
              point.confidence >= 0.15 else {
            return nil
        }
        return point.location
    }

    private func gesturePoint(_ point: CGPoint?) -> GesturePoint2D? {
        point.map { GesturePoint2D(x: Double($0.x), y: Double($0.y)) }
    }

    private func distance(_ first: CGPoint, _ second: CGPoint) -> CGFloat {
        hypot(first.x - second.x, first.y - second.y)
    }
}

final class HandPoseSceneRenderer: @unchecked Sendable {
    private weak var arView: ARView?
    private var viewportSize: CGSize = .zero

    @MainActor
    func setARView(_ arView: ARView) {
        self.arView = arView
        self.viewportSize = arView.bounds.size
    }

    @MainActor
    func currentViewportSize() -> CGSize {
        if let arView {
            viewportSize = arView.bounds.size
        }
        return viewportSize
    }

    @MainActor
    func currentImageOrientation() -> CGImagePropertyOrientation {
        guard let interfaceOrientation = arView?.window?.windowScene?.interfaceOrientation else {
            return .right
        }

        switch interfaceOrientation {
        case .portrait:
            return .right
        case .portraitUpsideDown:
            return .left
        case .landscapeLeft:
            return .up
        case .landscapeRight:
            return .down
        default:
            return .right
        }
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
}

@MainActor
final class HandPoseCaptureManager: NSObject, @preconcurrency ARSessionDelegate {
    private let processor = HandPoseVisionProcessor()
    private let renderer = HandPoseSceneRenderer()
    private let strokeRecorder = StrokeRecorder()
    private var isPaused = false
    private var isCaptureActive = false
    private var isProcessingFrame = false
    private var lastProcessedTimestamp: TimeInterval?
    private var targetFrameRate: Double = 15

    var isPauseGestureEnabled = true
    var isStopGestureEnabled = true
    var isMarkGestureEnabled = true

    var onGestureCommand: (@MainActor @Sendable (UIGestureCommand) -> Void)?

    func setPaused(_ paused: Bool) async {
        self.isPaused = paused
    }

    func setCaptureActive(_ active: Bool) {
        isCaptureActive = active
        if !active {
            lastProcessedTimestamp = nil
        }
    }

    func setTargetFrameRate(_ framesPerSecond: Double) {
        targetFrameRate = max(1, framesPerSecond)
        lastProcessedTimestamp = nil
    }

    /// Reset gesture state so pre-existing hand in frame doesn't immediately trigger a command.
    func resetGestureState() async {
        await processor.reset()
    }

    func clearActiveStroke() async {
        await strokeRecorder.clearActiveStroke()
    }

    func clearStrokes() async {
        await strokeRecorder.clearActiveStroke()
    }

    /// Packaged sessions: write strokes to `session_…/strokes.json`. Pass `nil` for legacy Documents file.
    func setStrokeOutputURL(_ url: URL?) async {
        await strokeRecorder.setCaptureOutputURL(url)
    }

    /// Align stroke timestamps with ARKit time base when recording starts (first AR frame).
    func alignStrokeSessionStart(arTimestamp: TimeInterval) async {
        await strokeRecorder.beginSession(startedAt: arTimestamp)
    }

    func setARView(_ arView: ARView) {
        renderer.setARView(arView)
    }

    func getSessionStrokes() async -> [StrokeRecorder.Stroke] {
        await strokeRecorder.getSessionStrokes()
    }

    func session(_ session: ARSession, didUpdate frame: ARFrame) {
        guard isCaptureActive, !isProcessingFrame else { return }
        if let lastProcessedTimestamp,
           frame.timestamp - lastProcessedTimestamp < 1.0 / targetFrameRate {
            return
        }
        lastProcessedTimestamp = frame.timestamp
        isProcessingFrame = true

        let pixelBuffer = PixelBufferBox(frame.capturedImage)
        let orientation = renderer.currentImageOrientation()
        let frameTimestamp = frame.timestamp
        let viewportSize = renderer.currentViewportSize()
        let pauseEnabled = self.isPauseGestureEnabled
        let stopEnabled = self.isStopGestureEnabled
        let markEnabled = self.isMarkGestureEnabled

        Task(priority: .utility) {
            defer { self.isProcessingFrame = false }
            let result = await processor.processFrameForFingertipAndGestures(
                pixelBufferBox: pixelBuffer,
                orientation: orientation,
                timestamp: frameTimestamp,
                pauseEnabled: pauseEnabled,
                stopEnabled: stopEnabled,
                markEnabled: markEnabled
            )

            guard self.isCaptureActive else { return }

            if let command = result.command {
                self.onGestureCommand?(command)
            }

            guard !self.isPaused else {
                // Paused: keep gesture recognition active, but do not capture strokes.
                _ = await strokeRecorder.ingestMissing(timestamp: frameTimestamp)
                return
            }

            if let fingertip = result.fingertip {
                let screenPoint = CGPoint(
                    x: fingertip.x * viewportSize.width,
                    y: (1 - fingertip.y) * viewportSize.height
                )

                guard let worldTransform = await renderer.raycastWorldTransform(from: screenPoint) else {
                    _ = await strokeRecorder.ingestMissing(timestamp: frameTimestamp)
                    return
                }

                let worldPosition = simd_float3(
                    worldTransform.columns.3.x,
                    worldTransform.columns.3.y,
                    worldTransform.columns.3.z
                )

                _ = await strokeRecorder.ingestDetected(
                    position: worldPosition,
                    timestamp: frameTimestamp
                )
            } else {
                _ = await strokeRecorder.ingestMissing(timestamp: frameTimestamp)
            }
        }
    }
}

