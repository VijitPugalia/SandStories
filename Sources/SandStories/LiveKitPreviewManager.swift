@preconcurrency import LiveKit
import Combine
import Foundation
import UIKit

@MainActor
final class LiveKitPreviewManager: ObservableObject {
    @Published private(set) var status: String = "Preview off"

    private var room: Room?

    func connect(settings: ExperimentServerSettings) async {
        guard settings.enabled, settings.previewEnabled, let baseURL = settings.baseURL() else {
            disconnect()
            return
        }

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
            try await room.localParticipant.setCamera(enabled: true)
            self.room = room
            status = "Preview live"
        } catch {
            status = "Preview failed: \(error.localizedDescription)"
        }
    }

    func disconnect() {
        Task { [room] in
            await room?.disconnect()
        }
        room = nil
        status = "Preview off"
    }
}
