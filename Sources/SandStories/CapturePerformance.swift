import ARKit
import AVFoundation
import AudioToolbox
import Combine
import Foundation
import UIKit

enum ZoomPreset: Double, CaseIterable, Identifiable, Sendable {
    case ultraWide = 0.5
    case one = 1
    case two = 2
    case three = 3

    var id: Double { rawValue }

    var title: String {
        rawValue == 1 ? "1×" : String(format: "%g×", rawValue)
    }
}

struct ZoomCaptureMetadata: Sendable {
    let displayZoomFactor: Double
    let deviceZoomFactor: Double
    let activeLens: String
}

/// Controls ARKit's underlying virtual back camera without opening another capture session.
@MainActor
final class CameraZoomController: ObservableObject {
    @Published private(set) var selectedPreset: ZoomPreset = .one
    @Published private(set) var supportedPresets: Set<ZoomPreset> = Set(ZoomPreset.allCases)
    @Published private(set) var activeLensDescription = "Wide"
    @Published private(set) var currentDeviceZoomFactor: CGFloat = 1
    @Published var isLocked = false {
        didSet { applySwitchingBehavior() }
    }

    private weak var captureDevice: AVCaptureDevice?
    private var lensMonitorTask: Task<Void, Never>?

    deinit {
        lensMonitorTask?.cancel()
    }

    func prepareForARSession() {
        guard let device = ARWorldTrackingConfiguration.configurableCaptureDeviceForPrimaryCamera else {
            supportedPresets = [.one]
            activeLensDescription = "Camera zoom unavailable"
            return
        }

        captureDevice = device
        let multiplier = max(device.displayVideoZoomFactorMultiplier, 0.0001)
        supportedPresets = Set(ZoomPreset.allCases.filter { preset in
            let factor = CGFloat(preset.rawValue) / multiplier
            return factor >= device.minAvailableVideoZoomFactor && factor <= device.maxAvailableVideoZoomFactor
        })

        apply(preset: selectedPreset, animated: false)
        applySwitchingBehavior()
        startLensMonitoring()
    }

    func select(_ preset: ZoomPreset) {
        guard supportedPresets.contains(preset), !isLocked else { return }
        selectedPreset = preset
        apply(preset: preset, animated: true)
    }

    func setLocked(_ locked: Bool) {
        isLocked = locked
    }

    func captureMetadata() -> ZoomCaptureMetadata {
        let multiplier = max(captureDevice?.displayVideoZoomFactorMultiplier ?? 1, 0.0001)
        let deviceFactor = captureDevice?.videoZoomFactor ?? currentDeviceZoomFactor
        return ZoomCaptureMetadata(
            displayZoomFactor: Double(deviceFactor * multiplier),
            deviceZoomFactor: Double(deviceFactor),
            activeLens: activeLensDescription
        )
    }

    private func apply(preset: ZoomPreset, animated: Bool) {
        guard let device = captureDevice else { return }
        let multiplier = max(device.displayVideoZoomFactorMultiplier, 0.0001)
        let requested = CGFloat(preset.rawValue) / multiplier
        let factor = min(max(requested, device.minAvailableVideoZoomFactor), device.maxAvailableVideoZoomFactor)

        do {
            try device.lockForConfiguration()
            if animated {
                device.ramp(toVideoZoomFactor: factor, withRate: 5)
            } else {
                device.videoZoomFactor = factor
            }
            device.unlockForConfiguration()
            currentDeviceZoomFactor = factor
            refreshActiveLens()
        } catch {
            activeLensDescription = "Zoom unavailable"
        }
    }

    private func applySwitchingBehavior() {
        guard let device = captureDevice,
              device.primaryConstituentDeviceSwitchingBehavior != .unsupported else { return }

        do {
            try device.lockForConfiguration()
            device.setPrimaryConstituentDeviceSwitchingBehavior(
                isLocked ? .locked : .auto,
                restrictedSwitchingBehaviorConditions: []
            )
            device.unlockForConfiguration()
        } catch {
            // Zoom still works on devices that don't expose constituent locking.
        }
    }

    private func startLensMonitoring() {
        lensMonitorTask?.cancel()
        lensMonitorTask = Task { [weak self] in
            while !Task.isCancelled {
                self?.refreshActiveLens()
                try? await Task.sleep(for: .seconds(1))
            }
        }
    }

    private func refreshActiveLens() {
        guard let device = captureDevice else { return }
        currentDeviceZoomFactor = device.videoZoomFactor
        let activeDevice = device.activePrimaryConstituent ?? device
        switch activeDevice.deviceType {
        case .builtInUltraWideCamera:
            activeLensDescription = "Ultra Wide"
        case .builtInTelephotoCamera:
            activeLensDescription = "Telephoto"
        case .builtInWideAngleCamera:
            if selectedPreset.rawValue > 1 {
                activeLensDescription = "Wide · \(selectedPreset.title) crop"
            } else {
                activeLensDescription = "Wide"
            }
        default:
            activeLensDescription = activeDevice.localizedName
        }
    }
}

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
