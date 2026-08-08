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
    private var openPalmStartedAt: TimeInterval?
    private var gestureCooldownUntil: TimeInterval = 0
    
    // Separate wrist histories for still-palm check vs wave check
    private var pauseWristXHistory: [CGFloat] = []
    private var pauseWristYHistory: [CGFloat] = []
    private var waveWristXHistory: [CGFloat] = []
    private var waveWristYHistory: [CGFloat] = []
    
    // Tap / Pinch state
    private var lastPinchActive = false
    private var pinchTimestamps: [TimeInterval] = []
    private var waveTimestamps: [TimeInterval] = []

    init() {
        request.maximumHandCount = 1
    }

    /// Reset all gesture-recognition state so no stale commands fire.
    func reset() {
        openPalmStartedAt = nil
        gestureCooldownUntil = ProcessInfo.processInfo.systemUptime + 2
        pauseWristXHistory.removeAll()
        pauseWristYHistory.removeAll()
        waveWristXHistory.removeAll()
        waveWristYHistory.removeAll()
        lastPinchActive = false
        pinchTimestamps.removeAll()
        waveTimestamps.removeAll()
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
        // Process every frame — actor already serializes concurrent requests.
        let handler = VNImageRequestHandler(cvPixelBuffer: pixelBufferBox.pixelBuffer, orientation: orientation)
        do {
            try handler.perform([request])
        } catch {
            print("HandPoseVisionProcessor perform error: \(error)")
            return DetectionResult(fingertip: nil, command: nil)
        }

        let observations = request.results ?? []
        guard let obs = observations.first else {
            openPalmStartedAt = nil
            if !pauseWristXHistory.isEmpty { pauseWristXHistory.removeFirst() }
            if !pauseWristYHistory.isEmpty { pauseWristYHistory.removeFirst() }
            if !waveWristXHistory.isEmpty { waveWristXHistory.removeFirst() }
            if !waveWristYHistory.isEmpty { waveWristYHistory.removeFirst() }
            return DetectionResult(fingertip: nil, command: nil)
        }
        let trackedIndexPoint = try? obs.recognizedPoint(.indexTip)
        let trackedFingertip = trackedIndexPoint.flatMap {
            $0.confidence >= 0.15 ? $0.location : nil
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
            openPalmStartedAt = nil
            if !pauseWristXHistory.isEmpty { pauseWristXHistory.removeFirst() }
            if !pauseWristYHistory.isEmpty { pauseWristYHistory.removeFirst() }
            if !waveWristXHistory.isEmpty { waveWristXHistory.removeFirst() }
            if !waveWristYHistory.isEmpty { waveWristYHistory.removeFirst() }
            return DetectionResult(fingertip: trackedFingertip, command: nil)
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

        // Update wrist movement histories
        if isOpenPalm {
            pauseWristXHistory.append(wLoc.x)
            pauseWristYHistory.append(wLoc.y)
            if pauseWristXHistory.count > 90 {
                pauseWristXHistory.removeFirst()
            }
            if pauseWristYHistory.count > 90 {
                pauseWristYHistory.removeFirst()
            }
            
            waveWristXHistory.append(wLoc.x)
            waveWristYHistory.append(wLoc.y)
            if waveWristXHistory.count > 30 {
                waveWristXHistory.removeFirst()
            }
            if waveWristYHistory.count > 30 {
                waveWristYHistory.removeFirst()
            }
        } else {
            if !pauseWristXHistory.isEmpty { pauseWristXHistory.removeFirst() }
            if !pauseWristYHistory.isEmpty { pauseWristYHistory.removeFirst() }
            if !waveWristXHistory.isEmpty { waveWristXHistory.removeFirst() }
            if !waveWristYHistory.isEmpty { waveWristYHistory.removeFirst() }
        }

        // Heuristic 1: Open Palm held for three elapsed seconds, independent of frame rate.
        if isOpenPalm && pauseEnabled {
            if openPalmStartedAt == nil {
                openPalmStartedAt = timestamp
            }
            if timestamp >= gestureCooldownUntil,
               let openPalmStartedAt,
               timestamp - openPalmStartedAt >= 3 {
                let rangeX = (pauseWristXHistory.max() ?? 0) - (pauseWristXHistory.min() ?? 0)
                let rangeY = (pauseWristYHistory.max() ?? 0) - (pauseWristYHistory.min() ?? 0)
                self.openPalmStartedAt = nil

                if rangeX < 0.08 && rangeY < 0.08 {
                    gestureCooldownUntil = timestamp + 2
                    pauseWristXHistory.removeAll()
                    pauseWristYHistory.removeAll()
                    command = .pause
                }
            }
        } else {
            openPalmStartedAt = nil
        }

        // Heuristic 2: Open Hand Wave (moving side-to-side, 3 times to Stop)
        if isOpenPalm && stopEnabled {
            if command == nil && timestamp >= gestureCooldownUntil && waveWristXHistory.count >= 20 {
                let minX = waveWristXHistory.min() ?? 0
                let maxX = waveWristXHistory.max() ?? 0
                if (maxX - minX) > 0.18 {
                    var directionChanges = 0
                    var lastDelta: CGFloat = 0
                    for i in 1..<waveWristXHistory.count {
                        let delta = waveWristXHistory[i] - waveWristXHistory[i-1]
                        if abs(delta) > 0.005 {
                            if (delta > 0 && lastDelta < 0) || (delta < 0 && lastDelta > 0) {
                                directionChanges += 1
                            }
                            lastDelta = delta
                        }
                    }
                    if directionChanges >= 3 {
                        waveWristXHistory.removeAll()
                        waveWristYHistory.removeAll()
                        
                        waveTimestamps.append(timestamp)
                        waveTimestamps = waveTimestamps.filter { timestamp - $0 < 4.0 }
                        
                        if waveTimestamps.count >= 3 {
                            waveTimestamps.removeAll()
                            gestureCooldownUntil = timestamp + 2
                            openPalmStartedAt = nil
                            command = .stop
                        }
                    }
                }
            }
        }

        // Heuristic 3: One-Finger Triple Tap (Mark Segment)
        let isOneFingerExtended = isIndexExtended && !isMiddleExtended && !isRingExtended && !isLittleExtended
        let pinchActive = distance(iTip, tTip) < 0.05

        if isOneFingerExtended && markEnabled {
            if pinchActive && !lastPinchActive {
                pinchTimestamps.append(timestamp)
                pinchTimestamps = pinchTimestamps.filter { timestamp - $0 < 2.0 }
                if command == nil && timestamp >= gestureCooldownUntil && pinchTimestamps.count >= 3 {
                    pinchTimestamps.removeAll()
                    command = .markSegment
                    gestureCooldownUntil = timestamp + 2
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
        guard isCaptureActive, !isProcessingFrame else { return }
        if let lastProcessedTimestamp,
           frame.timestamp - lastProcessedTimestamp < 1.0 / targetFrameRate {
            return
        }
        lastProcessedTimestamp = frame.timestamp
        isProcessingFrame = true

        let pixelBuffer = PixelBufferBox(frame.capturedImage)
        let orientation: CGImagePropertyOrientation = .right
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
        }
    }
}

