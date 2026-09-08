import Combine
import CoreImage
import Foundation
import ImageIO

/// Encodes at most one preview frame at a time, away from the UI actor.
actor PreviewJPEGEncoder {
    private let context = CIContext(options: [.cacheIntermediates: false])
    private let colorSpace = CGColorSpace(name: CGColorSpace.sRGB)!

    func encode(_ buffer: PixelBufferBox, orientation: CGImagePropertyOrientation) -> Data? {
        let source = CIImage(cvPixelBuffer: buffer.pixelBuffer).oriented(orientation)
        let scale = min(1, 640 / max(source.extent.width, source.extent.height))
        let image = source.transformed(by: CGAffineTransform(scaleX: scale, y: scale))
        return context.jpegRepresentation(of: image, colorSpace: colorSpace, options: [
            CIImageRepresentationOption(rawValue: kCGImageDestinationLossyCompressionQuality as String): 0.65
        ])
    }
}

@MainActor
final class TunnelPreviewManager: ObservableObject {
    @Published private(set) var status = "Preview off"
    private let encoder = PreviewJPEGEncoder()
    private var connectionTask: Task<Void, Never>?
    private var socket: URLSessionWebSocketTask?
    private var generation = UUID()
    private var viewerCount = 0
    private var awaitingAck = false
    private var sentAt: TimeInterval = 0
    private var lastFrameTimestamp: TimeInterval = 0
    private var fps: Double = 5

    func start(url: URL, fps: Double) {
        stop()
        self.fps = min(15, max(1, fps))
        let current = generation
        connectionTask = Task { [weak self] in
            guard let self else { return }
            while !Task.isCancelled, generation == current {
                viewerCount = 0
                awaitingAck = false
                let connection = UUID()
                activeConnection = connection
                let task = URLSession.shared.webSocketTask(with: url)
                socket = task
                status = "Tunnel preview connecting"
                task.resume()
                let heartbeat = Task { [weak self] in
                    while !Task.isCancelled {
                        do { try await Task.sleep(nanoseconds: 5_000_000_000) } catch { return }
                        guard let self, self.generation == current else { return }
                        if self.awaitingAck, ProcessInfo.processInfo.systemUptime - self.sentAt > 10 {
                            task.cancel(with: .goingAway, reason: nil)
                            return
                        }
                        do { try await task.send(.string("ping")) }
                        catch { task.cancel(with: .goingAway, reason: nil); return }
                    }
                }
                do {
                    while !Task.isCancelled, generation == current {
                        let message = try await task.receive()
                        guard generation == current, activeConnection == connection, !Task.isCancelled else { break }
                        guard case .string(let text) = message,
                              let data = text.data(using: .utf8),
                              let json = try JSONSerialization.jsonObject(with: data) as? [String: Any] else { continue }
                        if json["type"] as? String == "preview_demand" {
                            viewerCount = (json["viewers"] as? Int) ?? 0
                            status = viewerCount > 0 ? "Tunnel preview live" : "Tunnel preview waiting for viewer"
                        } else if json["type"] as? String == "frame_ack" {
                            awaitingAck = false
                        }
                    }
                } catch {
                    if generation == current, !Task.isCancelled { status = "Tunnel preview disconnected; retrying" }
                }
                heartbeat.cancel()
                task.cancel(with: .goingAway, reason: nil)
                guard generation == current, !Task.isCancelled else { return }
                activeConnection = UUID()
                socket = nil
                viewerCount = 0
                do { try await Task.sleep(nanoseconds: 1_500_000_000) } catch { return }
            }
        }
    }

    private var activeConnection = UUID()

    func capture(_ buffer: CVPixelBuffer, timestamp: TimeInterval, orientation: CGImagePropertyOrientation) {
        guard viewerCount > 0, !awaitingAck, let socket,
              timestamp - lastFrameTimestamp >= 1 / fps else { return }
        lastFrameTimestamp = timestamp
        awaitingAck = true
        sentAt = ProcessInfo.processInfo.systemUptime
        let current = generation
        let connection = activeConnection
        let boxed = PixelBufferBox(buffer)
        Task {
            let data = await encoder.encode(boxed, orientation: orientation)
            guard generation == current, activeConnection == connection else { return }
            guard let data, data.count <= 512 * 1024 else {
                awaitingAck = false
                status = "Tunnel preview frame could not be encoded"
                return
            }
            do { try await socket.send(.data(data)) }
            catch { socket.cancel(with: .goingAway, reason: nil) }
        }
    }

    func stop() {
        generation = UUID()
        activeConnection = UUID()
        connectionTask?.cancel()
        connectionTask = nil
        socket?.cancel(with: .goingAway, reason: nil)
        socket = nil
        viewerCount = 0
        awaitingAck = false
        lastFrameTimestamp = 0
        status = "Preview off"
    }
}
