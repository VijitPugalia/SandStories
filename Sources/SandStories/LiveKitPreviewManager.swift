@preconcurrency import LiveKit
import ARKit
import Combine
import Foundation
import UIKit

@MainActor
final class LiveKitPreviewManager: ObservableObject {
    @Published private(set) var status: String = "Preview off"

    private var generation = UUID()
    private var thermalSuspended = false
    private var nextPublishAttempt: TimeInterval = 0
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

        guard !thermalSuspended else { return }
        disconnect()
        let current = generation

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
            let (data, response) = try await URLSession.shared.data(from: tokenURL)
            guard generation == current, !Task.isCancelled else { return }
            guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
                status = "Preview token request rejected"
                return
            }
            guard let json = try JSONSerialization.jsonObject(with: data) as? [String: Any],
                  let livekitURL = json["url"] as? String,
                  let token = json["token"] as? String else {
                status = "Preview token failed"
                return
            }

            guard let endpoint = URLComponents(string: livekitURL),
                  ["ws", "wss"].contains(endpoint.scheme ?? ""),
                  let host = endpoint.host,
                  !["localhost", "127.0.0.1", "::1", "[::1]", "0.0.0.0"].contains(host.lowercased()) else {
                status = "Set LIVEKIT_URL to the server's reachable LAN address"
                return
            }
            let room = Room()
            self.room = room
            try await room.connect(url: livekitURL, token: token)
            guard generation == current, !Task.isCancelled else { await room.disconnect(); return }

            let track = LocalVideoTrack.createBufferTrack(
                name: "SandStories AR preview",
                source: .camera,
                options: BufferCaptureOptions(dimensions: Dimensions(width: 640, height: 480), fps: 10)
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
            guard generation == current, !Task.isCancelled else { return }
            disconnect()
            status = "Preview failed: \(error.localizedDescription)"
        }
    }

    /// Reuses ARKit's camera frame at 10 fps instead of opening a second AVCaptureSession.
    func capture(pixelBuffer: CVPixelBuffer, timestamp: TimeInterval) {
        guard let room, let bufferCapturer, let videoTrack else { return }
        guard !room.remoteParticipants.isEmpty else {
            if status != "Preview waiting for viewer" { status = "Preview waiting for viewer" }
            return
        }
        if isPublished, status != "Preview live" { status = "Preview live" }
        guard timestamp - lastFrameTimestamp >= 0.1 else { return }
        lastFrameTimestamp = timestamp

        bufferCapturer.capture(pixelBuffer, timeStampNs: Int64(timestamp * 1_000_000_000))

        guard !isPublished, !isPublishing, timestamp >= nextPublishAttempt else { return }
        let current = generation
        isPublishing = true
        Task {
            do {
                _ = try await room.localParticipant.publish(videoTrack: videoTrack, options: VideoPublishOptions(simulcast: false))
                guard generation == current else { return }
                isPublished = true
                status = "Preview live"
            } catch {
                guard generation == current else { return }
                nextPublishAttempt = timestamp + 3
                status = "Preview publish failed; retrying"
            }
            isPublishing = false
        }
    }

    func suspendForThermal() {
        thermalSuspended = true
        disconnect()
        status = "Preview paused for heat"
    }

    func resetThermalSuspension() { thermalSuspended = false }

    func disconnect() {
        generation = UUID()
        nextPublishAttempt = 0
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