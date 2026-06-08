import ARKit
import CoreVideo
import Foundation
import RealityKit
import Vision

enum UIGestureCommand: Sendable {
    case start
    case stop
    case pause
    case resume
    case markSegment
}

// Serializes Vision hand pose requests so we never build up a backlog.
actor HandPoseVisionProcessor {
    private let request = VNDetectHumanHandPoseRequest()

    // State for gesture detection
    private var openPalmConsecutiveFrames = 0
    private var gestureCooldownFrames = 0
    
    // Wave state
    private var wristXHistory: [CGFloat] = []
    
    // Tap / Pinch state
    private var lastPinchActive = false
    private var lastPinchTime: TimeInterval = 0

    init() {
        request.maximumHandCount = 1
    }

    /// Reset all gesture-recognition state so no stale commands fire.
    func reset() {
        openPalmConsecutiveFrames = 0
        gestureCooldownFrames = 60  // block gestures for ~2 s after reset
        wristXHistory.removeAll()
        lastPinchActive = false
        lastPinchTime = 0
    }

    struct DetectionResult: Sendable {
        let fingertip: CGPoint?
        let command: UIGestureCommand?
    }

    func processFrameForFingertipAndGestures(
        pixelBufferBox: PixelBufferBox,
        orientation: CGImagePropertyOrientation,
        timestamp: TimeInterval
    ) async -> DetectionResult {
        // Process every frame — actor already serializes concurrent requests.
        let handler = VNImageRequestHandler(cvPixelBuffer: pixelBufferBox.pixelBuffer, orientation: orientation)
        do {
            try handler.perform([request])
        } catch {
            print("HandPoseVisionProcessor perform error: \(error)")
            return DetectionResult(fingertip: nil, command: nil)
        }

        if gestureCooldownFrames > 0 {
            gestureCooldownFrames -= 1
        }

        let observations = request.results ?? []
        guard let obs = observations.first else {
            print("🖐️ No hand in frame")
            openPalmConsecutiveFrames = 0
            if !wristXHistory.isEmpty {
                wristXHistory.removeFirst()
            }
            return DetectionResult(fingertip: nil, command: nil)
        }

        guard let wrist = try? obs.recognizedPoint(.wrist), wrist.confidence >= 0.15,
              let thumbTip = try? obs.recognizedPoint(.thumbTip), thumbTip.confidence >= 0.15,
              let thumbIP = try? obs.recognizedPoint(.thumbIP), thumbIP.confidence >= 0.15,
              let indexTip = try? obs.recognizedPoint(.indexTip), indexTip.confidence >= 0.15,
              let indexMCP = try? obs.recognizedPoint(.indexMCP), indexMCP.confidence >= 0.15,
              let middleTip = try? obs.recognizedPoint(.middleTip), middleTip.confidence >= 0.15,
              let middleMCP = try? obs.recognizedPoint(.middleMCP), middleMCP.confidence >= 0.15,
              let ringTip = try? obs.recognizedPoint(.ringTip), ringTip.confidence >= 0.15,
              let ringMCP = try? obs.recognizedPoint(.ringMCP), ringMCP.confidence >= 0.15,
              let littleTip = try? obs.recognizedPoint(.littleTip), littleTip.confidence >= 0.15,
              let littleMCP = try? obs.recognizedPoint(.littleMCP), littleMCP.confidence >= 0.15
        else {
            // Log which landmarks are failing for debugging
            let wC = (try? obs.recognizedPoint(.wrist))?.confidence ?? 0
            let tC = (try? obs.recognizedPoint(.thumbTip))?.confidence ?? 0
            let iC = (try? obs.recognizedPoint(.indexTip))?.confidence ?? 0
            let mC = (try? obs.recognizedPoint(.middleTip))?.confidence ?? 0
            let rC = (try? obs.recognizedPoint(.ringTip))?.confidence ?? 0
            let lC = (try? obs.recognizedPoint(.littleTip))?.confidence ?? 0
            print("🖐️ Landmarks below threshold: wrist=\(String(format: "%.2f", wC)) thumb=\(String(format: "%.2f", tC)) index=\(String(format: "%.2f", iC)) mid=\(String(format: "%.2f", mC)) ring=\(String(format: "%.2f", rC)) little=\(String(format: "%.2f", lC))")
            openPalmConsecutiveFrames = 0
            if !wristXHistory.isEmpty {
                wristXHistory.removeFirst()
            }
            return DetectionResult(fingertip: nil, command: nil)
        }

        let wLoc = wrist.location
        let tTip = thumbTip.location
        let tIP = thumbIP.location
        let iTip = indexTip.location
        let iMCP = indexMCP.location
        let mTip = middleTip.location
        let mMCP = middleMCP.location
        let rTip = ringTip.location
        let rMCP = ringMCP.location
        let lTip = littleTip.location
        let lMCP = littleMCP.location

        let isThumbExtended = distance(tTip, wLoc) > distance(tIP, wLoc) * 1.1
        let isIndexExtended = distance(iTip, wLoc) > distance(iMCP, wLoc) * 1.2
        let isMiddleExtended = distance(mTip, wLoc) > distance(mMCP, wLoc) * 1.2
        let isRingExtended = distance(rTip, wLoc) > distance(rMCP, wLoc) * 1.2
        let isLittleExtended = distance(lTip, wLoc) > distance(lMCP, wLoc) * 1.2

        let isOpenPalm = isThumbExtended && isIndexExtended && isMiddleExtended && isRingExtended && isLittleExtended

        var command: UIGestureCommand? = nil

        // Heuristic 1: Open Palm (Hold 1.0 second = 30 frames)
        if isOpenPalm {
            openPalmConsecutiveFrames += 1
            if gestureCooldownFrames == 0 && openPalmConsecutiveFrames >= 30 {
                openPalmConsecutiveFrames = 0
                gestureCooldownFrames = 60
                wristXHistory.removeAll()
                command = .pause
            }
        } else {
            openPalmConsecutiveFrames = 0
        }

        // Heuristic 2: Open Hand Wave (moving side-to-side)
        if isOpenPalm {
            wristXHistory.append(wLoc.x)
            if wristXHistory.count > 30 {
                wristXHistory.removeFirst()
            }

            if command == nil && gestureCooldownFrames == 0 && wristXHistory.count == 30 {
                let minX = wristXHistory.min() ?? 0
                let maxX = wristXHistory.max() ?? 0
                if (maxX - minX) > 0.18 {
                    var directionChanges = 0
                    var lastDelta: CGFloat = 0
                    for i in 1..<wristXHistory.count {
                        let delta = wristXHistory[i] - wristXHistory[i-1]
                        if abs(delta) > 0.005 {
                            if (delta > 0 && lastDelta < 0) || (delta < 0 && lastDelta > 0) {
                                directionChanges += 1
                            }
                            lastDelta = delta
                        }
                    }
                    if directionChanges >= 3 {
                        wristXHistory.removeAll()
                        gestureCooldownFrames = 60
                        openPalmConsecutiveFrames = 0
                        command = .start
                    }
                }
            }
        } else {
            if !wristXHistory.isEmpty {
                wristXHistory.removeFirst()
            }
        }

        // Heuristic 3: Two-Finger Double Tap
        let isTwoFingersExtended = isIndexExtended && isMiddleExtended && !isRingExtended && !isLittleExtended
        let pinchActive = distance(iTip, tTip) < 0.05 && distance(mTip, tTip) < 0.05

        if isTwoFingersExtended {
            if pinchActive && !lastPinchActive {
                let deltaT = timestamp - lastPinchTime
                if deltaT < 1.2 && lastPinchTime > 0 {
                    lastPinchTime = 0
                    lastPinchActive = false
                    if command == nil && gestureCooldownFrames == 0 {
                        command = .markSegment
                        gestureCooldownFrames = 60
                    }
                } else {
                    lastPinchTime = timestamp
                }
            }
            lastPinchActive = pinchActive
        } else {
            lastPinchActive = false
        }

        return DetectionResult(fingertip: iTip, command: command)
    }

    private func distance(_ p1: CGPoint, _ p2: CGPoint) -> CGFloat {
        let dx = p1.x - p2.x
        let dy = p1.y - p2.y
        return sqrt(dx*dx + dy*dy)
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
            self?.currentStrokeAnchor = AnchorEntity(world: matrix_identity_float4x4)
        }
    }

    func appendStrokePoint(_ position: simd_float3) async {
        // Stroke points are persisted in strokes.json; avoid spawning a RealityKit entity per point.
        await renderFingertip(at: position)
    }

    private func renderFingertip(at position: simd_float3) async {
        await MainActor.run { [weak self] in
            guard let self, let arView else { return }

            if let fingertipAnchor {
                fingertipAnchor.transform.translation = position
                return
            }

            let anchor = AnchorEntity(world: matrix_identity_float4x4)
            anchor.transform.translation = position

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

@MainActor
final class HandPoseCaptureManager: NSObject, @preconcurrency ARSessionDelegate {
    private let processor = HandPoseVisionProcessor()
    private let renderer = HandPoseSceneRenderer()
    private let strokeRecorder = StrokeRecorder()
    private var isProcessing = false
    private var isPaused = false

    var onGestureCommand: (@MainActor @Sendable (UIGestureCommand) -> Void)?

    func setPaused(_ paused: Bool) async {
        self.isPaused = paused
    }

    /// Reset gesture state so pre-existing hand in frame doesn't immediately trigger a command.
    func resetGestureState() async {
        await processor.reset()
    }

    func clearActiveStroke() async {
        await strokeRecorder.clearActiveStroke()
    }

    func clearStrokes() async {
        await renderer.clearStrokes()
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
        guard !isProcessing else { return }
        isProcessing = true

        let pixelBuffer = PixelBufferBox(frame.capturedImage)
        let orientation: CGImagePropertyOrientation = .right
        let frameTimestamp = frame.timestamp
        let viewportSize = renderer.currentViewportSize()

        Task(priority: .userInitiated) {
            let result = await processor.processFrameForFingertipAndGestures(
                pixelBufferBox: pixelBuffer,
                orientation: orientation,
                timestamp: frameTimestamp
            )

            if let command = result.command {
                self.onGestureCommand?(command)
            }

            guard !self.isPaused else {
                // Paused: Render tracker only, no stroke capture.
                if let fingertip = result.fingertip {
                    let screenPoint = CGPoint(
                        x: fingertip.x * viewportSize.width,
                        y: (1 - fingertip.y) * viewportSize.height
                    )
                    if let worldTransform = await renderer.raycastWorldTransform(from: screenPoint) {
                        await renderer.renderFingertip(worldTransform: worldTransform)
                    }
                }
                let missingEvent = await strokeRecorder.ingestMissing(timestamp: frameTimestamp)
                if case .finished = missingEvent {
                    await renderer.endStroke()
                }
                self.isProcessing = false
                return
            }

            if let fingertip = result.fingertip {
                let screenPoint = CGPoint(
                    x: fingertip.x * viewportSize.width,
                    y: (1 - fingertip.y) * viewportSize.height
                )

                guard let worldTransform = await renderer.raycastWorldTransform(from: screenPoint) else {
                    let missingEvent = await strokeRecorder.ingestMissing(timestamp: frameTimestamp)
                    if case .finished = missingEvent {
                        await renderer.endStroke()
                    }
                    self.isProcessing = false
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
            } else {
                let missingEvent = await strokeRecorder.ingestMissing(timestamp: frameTimestamp)
                if case .finished = missingEvent {
                    await renderer.endStroke()
                }
            }

            self.isProcessing = false
        }
    }
}

