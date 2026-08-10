import AudioToolbox
import Combine
import Foundation
import UIKit
enum CapturePerformanceMode: String, Sendable {
    case fullQuality
    case thermalReduced
}

@MainActor
final class ThermalMonitor: NSObject, ObservableObject {
    @Published private(set) var thermalState = ProcessInfo.processInfo.thermalState
    @Published var isPromptPresented = false

    private var lastAlertedState: ProcessInfo.ThermalState?
    private var isSessionActive = false

    override init() {
        super.init()
        NotificationCenter.default.addObserver(
            self,
            selector: #selector(thermalStateDidChange),
            name: ProcessInfo.thermalStateDidChangeNotification,
            object: nil
        )
    }

    deinit {
        NotificationCenter.default.removeObserver(self)
    }

    func evaluateForActiveSession() {
        isSessionActive = true
        evaluate(force: true)
    }

    func acknowledge() {
        isPromptPresented = false
    }

    func resetForNextSession() {
        isSessionActive = false
        isPromptPresented = false
        lastAlertedState = nil
    }

    @objc private func thermalStateDidChange() {
        evaluate(force: false)
    }

    private func evaluate(force: Bool) {
        let state = ProcessInfo.processInfo.thermalState
        thermalState = state

        guard isSessionActive else { return }
        guard state == .serious || state == .critical else { return }
        let escalatedToCritical = state == .critical && lastAlertedState != .critical
        guard force || lastAlertedState == nil || escalatedToCritical else { return }

        lastAlertedState = state
        UINotificationFeedbackGenerator().notificationOccurred(.warning)
        AudioServicesPlayAlertSound(SystemSoundID(1005))
        isPromptPresented = true
    }
}
