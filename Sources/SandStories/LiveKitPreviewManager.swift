@preconcurrency import LiveKit
import ARKit
import Combine
import Foundation
import UIKit

@MainActor
final class LiveKitPreviewManager: ObservableObject {
    @Published private(set) var status: String = "Preview off"

    private var room: Room?
    private var videoTrack: LocalVideoTrack?
    private var bufferCapturer: BufferCapturer?
    private var isPublishing = false
    private var isPublished = false
    private var lastFrameTimestamp: TimeInterval = 0

    func connect(settings: ExperimentServerSettings) async {
        guard settings.enabled, settings.previewEnabled, let baseURL = settings.baseURL() else {
            disconnect()
            return
        }

        disconnect()

        do {
            let deviceId = UIDevice.current.identifierForVendor?.uuidString ?? "sandstories-device"
            var components = URLComponents(url: baseURL.appendingPathComponent("api/livekit/token"), resolvingAgainstBaseURL: false)
            components?.queryItems = [
                .init(name: "room", value: "device_\(deviceId)"),
                .init(name: "identity", value: "device_\(deviceId)"),
                .init(name: "role", value: "device"),
                .init(name: "token", value: settings.deviceToken)
            ]
            guard let tokenURL = components?.url else { return }
            let (data, _) = try await URLSession.shared.data(from: tokenURL)
            guard let json = try JSONSerialization.jsonObject(with: data) as? [String: Any],
                  let livekitURL = json["url"] as? String,
                  let token = json["token"] as? String else {
                status = "Preview token failed"
                return
            }

            let room = Room()
            try await room.connect(url: livekitURL, token: token)

            let track = LocalVideoTrack.createBufferTrack(
                name: "SandStories AR preview",
                source: .camera
            )
            guard let capturer = track.capturer as? BufferCapturer else {
                await room.disconnect()
                status = "Preview setup failed"
                return
            }

            self.room = room
            videoTrack = track
            bufferCapturer = capturer
            status = "Preview ready"
        } catch {
            status = "Preview failed: \(error.localizedDescription)"
        }
    }

    /// Reuses ARKit's camera frame at 10 fps instead of opening a second AVCaptureSession.
    func capture(pixelBuffer: CVPixelBuffer, timestamp: TimeInterval) {
        guard room != nil, let bufferCapturer, let videoTrack else { return }
        guard timestamp - lastFrameTimestamp >= 0.1 else { return }
        lastFrameTimestamp = timestamp

        bufferCapturer.capture(pixelBuffer, timeStampNs: Int64(timestamp * 1_000_000_000))

        guard !isPublished, !isPublishing, let room else { return }
        isPublishing = true
        Task {
            do {
                _ = try await room.localParticipant.publish(videoTrack: videoTrack)
                isPublished = true
                status = "Preview live"
            } catch {
                status = "Preview publish failed"
            }
            isPublishing = false
        }
    }

    func suspendForThermal() {
        disconnect()
        status = "Preview paused for heat"
    }

    func disconnect() {
        let roomToClose = room
        Task {
            await roomToClose?.disconnect()
        }
        room = nil
        videoTrack = nil
        bufferCapturer = nil
        isPublishing = false
        isPublished = false
        lastFrameTimestamp = 0
        status = "Preview off"
    }
}

/// Small ARSession delegate that feeds the already-captured AR frame to LiveKit.
@MainActor
final class ARFramePreviewForwarder: NSObject, @preconcurrency ARSessionDelegate {
    weak var previewManager: LiveKitPreviewManager?

    init(previewManager: LiveKitPreviewManager) {
        self.previewManager = previewManager
        super.init()
    }

    func session(_ session: ARSession, didUpdate frame: ARFrame) {
        previewManager?.capture(pixelBuffer: frame.capturedImage, timestamp: frame.timestamp)
    }
}