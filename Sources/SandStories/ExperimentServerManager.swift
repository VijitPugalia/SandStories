import Combine
import Foundation
import UIKit

@MainActor
final class ExperimentServerSettings: ObservableObject {
    private let defaults = UserDefaults.standard
    private let enabledKey = "experiment.enabled"
    private let serverURLKey = "experiment.serverURL"
    private let deviceTokenKey = "experiment.deviceToken"
    private let deviceNameKey = "experiment.deviceName"
    private let previewEnabledKey = "experiment.previewEnabled"

    @Published var enabled: Bool { didSet { defaults.set(enabled, forKey: enabledKey) } }
    @Published var serverURL: String { didSet { defaults.set(serverURL, forKey: serverURLKey) } }
    @Published var deviceToken: String { didSet { defaults.set(deviceToken, forKey: deviceTokenKey) } }
    @Published var deviceName: String { didSet { defaults.set(deviceName, forKey: deviceNameKey) } }
    @Published var previewEnabled: Bool { didSet { defaults.set(previewEnabled, forKey: previewEnabledKey) } }

    init() {
        enabled = defaults.bool(forKey: enabledKey)
        serverURL = defaults.string(forKey: serverURLKey) ?? "http://127.0.0.1:8080"
        deviceToken = defaults.string(forKey: deviceTokenKey) ?? "field-device"
        deviceName = defaults.string(forKey: deviceNameKey) ?? UIDevice.current.name
        previewEnabled = defaults.object(forKey: previewEnabledKey) as? Bool ?? true
    }

    func baseURL() -> URL? {
        URL(string: serverURL.trimmingCharacters(in: .whitespacesAndNewlines))
    }

    func websocketURL(deviceId: String) -> URL? {
        guard var components = URLComponents(string: serverURL.trimmingCharacters(in: .whitespacesAndNewlines)) else { return nil }
        components.scheme = components.scheme == "https" ? "wss" : "ws"
        components.path = "/ws/device/\(deviceId)"
        components.queryItems = [
            .init(name: "token", value: deviceToken),
            .init(name: "name", value: deviceName)
        ]
        return components.url
    }
}

@MainActor
final class RemoteControlManager: ObservableObject {
    @Published private(set) var status: String = "Remote off"

    private var webSocket: URLSessionWebSocketTask?
    private weak var coordinator: RecordingCoordinator?
    private var settings: ExperimentServerSettings?
    private var heartbeatTask: Task<Void, Never>?

    func start(settings: ExperimentServerSettings, coordinator: RecordingCoordinator) {
        self.settings = settings
        self.coordinator = coordinator
        guard settings.enabled else {
            stop()
            return
        }
        connect()
    }

    func stop() {
        heartbeatTask?.cancel()
        heartbeatTask = nil
        webSocket?.cancel(with: .goingAway, reason: nil)
        webSocket = nil
        status = "Remote off"
    }

    func sendStatus() {
        guard let coordinator, let settings else { return }
        let payload: [String: Any] = [
            "type": "device_status",
            "deviceName": settings.deviceName,
            "recording": coordinator.isCaptureRecording,
            "paused": coordinator.isCapturePaused,
            "uploadStatus": coordinator.uploadStatus ?? "",
            "timestampUnix": Date().timeIntervalSince1970
        ]
        sendJSON(payload)
    }

    private func connect() {
        guard let settings, let url = settings.websocketURL(deviceId: deviceId()) else { return }
        webSocket?.cancel(with: .goingAway, reason: nil)
        let task = URLSession.shared.webSocketTask(with: url)
        webSocket = task
        task.resume()
        status = "Remote connected"
        receiveLoop()
        heartbeatTask = Task { [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(nanoseconds: 2_000_000_000)
                await MainActor.run { self?.sendStatus() }
            }
        }
    }

    private func receiveLoop() {
        webSocket?.receive { [weak self] result in
            Task { @MainActor in
                guard let self else { return }
                switch result {
                case .success(let message):
                    if case .string(let text) = message {
                        await self.handleMessage(text)
                    }
                    self.receiveLoop()
                case .failure(let error):
                    self.status = "Remote disconnected: \(error.localizedDescription)"
                    try? await Task.sleep(nanoseconds: 1_500_000_000)
                    self.connect()
                }
            }
        }
    }

    private func handleMessage(_ text: String) async {
        guard let data = text.data(using: .utf8),
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              json["type"] as? String == "command",
              let commandId = json["commandId"] as? String,
              let name = json["name"] as? String else { return }

        sendJSON(["type": "command_ack", "commandId": commandId, "status": "accepted"])
        do {
            try await runCommand(name)
            sendJSON(["type": "command_result", "commandId": commandId, "status": "completed"])
        } catch {
            sendJSON(["type": "command_result", "commandId": commandId, "status": "failed", "error": error.localizedDescription])
        }
    }

    private func runCommand(_ name: String) async throws {
        guard let coordinator else { return }
        switch name {
        case "start_recording": await coordinator.startFromRemote(recordAudio: true)
        case "stop_recording": await coordinator.stopFromRemote()
        case "pause_recording": await coordinator.pauseCaptureSession()
        case "resume_recording": await coordinator.resumeCaptureSession()
        case "mark_segment": await coordinator.markSegment()
        case "upload_last_session": await coordinator.uploadLastSessionFromRemote()
        case "ping": sendStatus()
        default: break
        }
    }

    private func sendJSON(_ object: [String: Any]) {
        guard let data = try? JSONSerialization.data(withJSONObject: object),
              let text = String(data: data, encoding: .utf8) else { return }
        webSocket?.send(.string(text)) { _ in }
    }

    private func deviceId() -> String {
        UIDevice.current.identifierForVendor?.uuidString ?? "sandstories-device"
    }
}
