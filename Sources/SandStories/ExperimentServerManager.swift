import Combine
import Foundation
import UIKit

enum PreviewTransport: String, CaseIterable, Identifiable {
    case tunnel
    case liveKit
    var id: String { rawValue }
    var label: String { self == .tunnel ? "Console Tunnel" : "LiveKit" }
}

@MainActor
final class ExperimentServerSettings: ObservableObject {
    private let defaults = UserDefaults.standard
    private let enabledKey = "experiment.enabled"
    private let serverURLKey = "experiment.serverURL"
    private let deviceTokenKey = "experiment.deviceToken"
    private let deviceNameKey = "experiment.deviceName"
    private let previewEnabledKey = "experiment.previewEnabled"

    @Published var previewTransport: PreviewTransport { didSet { defaults.set(previewTransport.rawValue, forKey: "experiment.previewTransport") } }
    @Published var previewFPS: Double { didSet { defaults.set(previewFPS, forKey: "experiment.previewFPS") } }

    @Published var enabled: Bool { didSet { defaults.set(enabled, forKey: enabledKey) } }
    @Published var serverURL: String { didSet { defaults.set(serverURL, forKey: serverURLKey) } }
    @Published var deviceToken: String { didSet { defaults.set(deviceToken, forKey: deviceTokenKey) } }
    @Published var deviceName: String { didSet { defaults.set(deviceName, forKey: deviceNameKey) } }
    @Published var previewEnabled: Bool { didSet { defaults.set(previewEnabled, forKey: previewEnabledKey) } }

    init() {
        previewTransport = PreviewTransport(rawValue: defaults.string(forKey: "experiment.previewTransport") ?? "") ?? .tunnel
        let storedFPS = (defaults.object(forKey: "experiment.previewFPS") as? Double) ?? 5
        previewFPS = storedFPS.isFinite ? min(15, max(1, storedFPS)) : 5
        enabled = defaults.bool(forKey: enabledKey)
        serverURL = defaults.string(forKey: serverURLKey) ?? ""
        deviceToken = defaults.string(forKey: deviceTokenKey) ?? "field-device"
        deviceName = defaults.string(forKey: deviceNameKey) ?? UIDevice.current.name
        previewEnabled = defaults.object(forKey: previewEnabledKey) as? Bool ?? true
    }

    func baseURL() -> URL? {
        guard let url = URL(string: serverURL.trimmingCharacters(in: .whitespacesAndNewlines)),
              ["http", "https"].contains(url.scheme?.lowercased() ?? ""),
              let host = url.host, !host.isEmpty,
              !["localhost", "127.0.0.1", "::1", "[::1]", "0.0.0.0"].contains(host.lowercased()) else { return nil }
        return url
    }

    func previewWebSocketURL(deviceId: String) -> URL? {
        guard let base = baseURL(),
              var url = URLComponents(url: base.appendingPathComponent("ws/preview/device/\(deviceId)"), resolvingAgainstBaseURL: false) else { return nil }
        url.scheme = base.scheme?.lowercased() == "https" ? "wss" : "ws"
        url.queryItems = [.init(name: "token", value: deviceToken)]
        return url.url
    }

    func uploadURL() -> URL? {
        guard let base = baseURL(),
              var url = URLComponents(url: base.appendingPathComponent("upload"), resolvingAgainstBaseURL: false) else { return nil }
        url.queryItems = [.init(name: "token", value: deviceToken)]
        return url.url
    }

    func websocketURL(deviceId: String) -> URL? {
        guard let base = baseURL(),
              var components = URLComponents(url: base, resolvingAgainstBaseURL: false) else { return nil }
        components.scheme = components.scheme?.lowercased() == "https" ? "wss" : "ws"
        let prefix = components.path.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        components.path = (prefix.isEmpty ? "" : "/" + prefix) + "/ws/device/\(deviceId)"
        components.queryItems = [
            .init(name: "token", value: deviceToken),
            .init(name: "name", value: deviceName)
        ]
        return components.url
    }
}

@MainActor
final class RemoteControlManager: ObservableObject {
    @Published private(set) var status = "Remote off"
    private weak var coordinator: RecordingCoordinator?
    private var connectionTask: Task<Void, Never>?
    private var webSocket: URLSessionWebSocketTask?
    private var generation = UUID()
    private var completed: [String: [String: Any]] = [:]
    private var completedOrder: [String] = []

    func start(settings: ExperimentServerSettings, coordinator: RecordingCoordinator) {
        stop()
        self.coordinator = coordinator
        guard settings.enabled else { return }
        guard let url = settings.websocketURL(deviceId: UIDevice.current.identifierForVendor?.uuidString ?? "sandstories-device") else {
            status = "Enter the console computer's LAN address (not localhost)"
            return
        }
        let current = generation
        let name = settings.deviceName
        let uploadEndpoint = settings.uploadURL()
        connectionTask = Task { [weak self] in
            guard let self else { return }
            while !Task.isCancelled, self.generation == current {
                let socket = URLSession.shared.webSocketTask(with: url)
                self.webSocket = socket
                self.status = "Remote connecting"
                socket.resume()
                let heartbeat = Task { [weak self] in
                    while !Task.isCancelled {
                        do { try await Task.sleep(nanoseconds: 2_000_000_000) } catch { return }
                        guard let self, self.generation == current else { return }
                        do { try await self.sendStatus(on: socket, name: name) }
                        catch { socket.cancel(with: .goingAway, reason: nil); return }
                    }
                }
                do {
                    try await self.sendStatus(on: socket, name: name)
                    guard self.generation == current, !Task.isCancelled else { heartbeat.cancel(); return }
                    self.status = "Remote connected"
                    while !Task.isCancelled, self.generation == current {
                        let message = try await socket.receive()
                        guard self.generation == current, !Task.isCancelled else { break }
                        if case .string(let text) = message {
                            try await self.handleMessage(text, on: socket, name: name, uploadEndpoint: uploadEndpoint)
                        }
                    }
                } catch {
                    if self.generation == current, !Task.isCancelled { self.status = "Remote disconnected; retrying" }
                }
                heartbeat.cancel()
                socket.cancel(with: .goingAway, reason: nil)
                guard self.generation == current, !Task.isCancelled else { return }
                do { try await Task.sleep(nanoseconds: 1_500_000_000) } catch { return }
            }
        }
    }

    func stop() {
        generation = UUID()
        connectionTask?.cancel()
        connectionTask = nil
        webSocket?.cancel(with: .goingAway, reason: nil)
        webSocket = nil
        status = "Remote off"
    }

    private func sendStatus(on socket: URLSessionWebSocketTask, name: String) async throws {
        guard let coordinator else { return }
        let snapshot = await coordinator.depthCaptureManager.benchmarkSnapshot()
        try await send([
            "type": "device_status", "deviceName": name,
            "recording": coordinator.isCaptureRecording, "paused": coordinator.isCapturePaused,
            "saving": coordinator.isSavingSession, "starting": coordinator.isStartingSession,
            "elapsedSeconds": coordinator.recordingElapsedSeconds(), "savedFrames": snapshot.framesWritten,
            "uploadStatus": coordinator.uploadStatus ?? "", "timestampUnix": Date().timeIntervalSince1970
        ], on: socket)
    }

    private func handleMessage(_ text: String, on socket: URLSessionWebSocketTask, name: String, uploadEndpoint: URL?) async throws {
        guard let data = text.data(using: .utf8),
              let json = try JSONSerialization.jsonObject(with: data) as? [String: Any],
              json["type"] as? String == "command",
              let id = json["commandId"] as? String,
              let command = json["name"] as? String else { return }
        if let previous = completed[id] { try await send(previous, on: socket); return }
        try await send(["type": "command_ack", "commandId": id, "status": "accepted"], on: socket)
        var result: [String: Any] = ["type": "command_result", "commandId": id, "status": "completed"]
        do {
            guard let coordinator else { throw RemoteCommandError("Capture controller unavailable") }
            try await coordinator.executeRemoteCommand(command, payload: (json["payload"] as? [String: Any]) ?? [:], uploadEndpoint: uploadEndpoint)
        } catch {
            result["status"] = "failed"
            result["error"] = error.localizedDescription
        }
        completed[id] = result
        completedOrder.append(id)
        if completedOrder.count > 128 { completed.removeValue(forKey: completedOrder.removeFirst()) }
        try await send(result, on: socket)
        try await sendStatus(on: socket, name: name)
    }

    private func send(_ object: [String: Any], on socket: URLSessionWebSocketTask) async throws {
        let data = try JSONSerialization.data(withJSONObject: object)
        try await socket.send(.string(String(decoding: data, as: UTF8.self)))
    }
}

struct RemoteCommandError: LocalizedError {
    let message: String
    init(_ message: String) { self.message = message }
    var errorDescription: String? { message }
}
