import ARKit
import AVFoundation
import AudioToolbox
import Combine
import Foundation
import OSLog
import UIKit

enum ZoomPreset: Double, CaseIterable, Identifiable, Sendable {
    case ultraWide = 0.5
    case one = 1
    case two = 2
    case three = 3

    var id: Double { rawValue }

    var title: String {
        switch self {
        case .ultraWide: ".5"
        case .one: "1×"
        case .two: "2"
        case .three: "3"
        }
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
    @Published private(set) var diagnosticSummary = "Camera not prepared"

    private var captureDevice: AVCaptureDevice?
    private var lensMonitorTask: Task<Void, Never>?
    private let logger = Logger(
        subsystem: Bundle.main.bundleIdentifier ?? "SandStories",
        category: "CameraZoom"
    )

    deinit {
        lensMonitorTask?.cancel()
    }

    func prepareForARSession() {
        guard let device = ARWorldTrackingConfiguration.configurableCaptureDeviceForPrimaryCamera else {
            captureDevice = nil
            supportedPresets = [.one]
            activeLensDescription = "ARKit camera unavailable"
            diagnosticSummary = "configurableCaptureDeviceForPrimaryCamera returned nil"
            logger.error("\(self.diagnosticSummary, privacy: .public)")
            return
        }

        captureDevice = device
        supportedPresets = Set(ZoomPreset.allCases)
        diagnosticSummary = diagnostics(for: device)
        logger.notice("prepared \(self.diagnosticSummary, privacy: .public)")
        apply(preset: selectedPreset)
        startLensMonitoring()
    }

    func select(_ preset: ZoomPreset) {
        selectedPreset = preset

        if captureDevice == nil {
            prepareForARSession()
            return
        }
        apply(preset: preset)
    }

    func captureMetadata() -> ZoomCaptureMetadata {
        let multiplier = displayZoomMultiplier(for: captureDevice)
        let deviceFactor = captureDevice?.videoZoomFactor ?? currentDeviceZoomFactor
        return ZoomCaptureMetadata(
            displayZoomFactor: Double(deviceFactor * multiplier),
            deviceZoomFactor: Double(deviceFactor),
            activeLens: activeLensDescription
        )
    }

    private func apply(preset: ZoomPreset) {
        guard let device = captureDevice
                ?? ARWorldTrackingConfiguration.configurableCaptureDeviceForPrimaryCamera else {
            activeLensDescription = "ARKit camera unavailable"
            logger.error("zoom tap \(preset.title, privacy: .public): no configurable ARKit camera")
            return
        }
        captureDevice = device

        let beforeFactor = device.videoZoomFactor
        let beforeLens = lensName(for: device.activePrimaryConstituent ?? device)
        let targetFactor = targetDeviceZoomFactor(for: preset, device: device)

        do {
            try device.lockForConfiguration()
            defer { device.unlockForConfiguration() }

            if device.primaryConstituentDeviceSwitchingBehavior != .unsupported {
                device.setPrimaryConstituentDeviceSwitchingBehavior(
                    .auto,
                    restrictedSwitchingBehaviorConditions: []
                )
            }
            device.cancelVideoZoomRamp()
            device.videoZoomFactor = targetFactor
            currentDeviceZoomFactor = device.videoZoomFactor
        } catch {
            activeLensDescription = "Zoom unavailable"
            logger.error(
                "zoom tap \(preset.title, privacy: .public) failed: \(error.localizedDescription, privacy: .public)"
            )
            return
        }

        refreshActiveLens()
        logger.notice(
            "zoom tap \(preset.title, privacy: .public) before=\(beforeFactor, privacy: .public) target=\(targetFactor, privacy: .public) applied=\(self.currentDeviceZoomFactor, privacy: .public) beforeLens=\(beforeLens, privacy: .public) active=\(self.activeLensDescription, privacy: .public)"
        )

        Task { [weak self, weak device] in
            try? await Task.sleep(for: .milliseconds(350))
            guard let self, let device else { return }
            self.refreshActiveLens()
            self.logger.notice(
                "zoom settled \(preset.title, privacy: .public) factor=\(device.videoZoomFactor, privacy: .public) active=\(self.activeLensDescription, privacy: .public)"
            )
        }
    }

    private func targetDeviceZoomFactor(
        for preset: ZoomPreset,
        device: AVCaptureDevice
    ) -> CGFloat {
        let wideBase = wideBaseZoomFactor(for: device)
        let switchFactors = device.virtualDeviceSwitchOverVideoZoomFactors.map {
            CGFloat($0.doubleValue)
        }

        var requested = CGFloat(preset.rawValue) * wideBase
        switch preset {
        case .ultraWide:
            requested = device.minAvailableVideoZoomFactor
        case .one:
            if let first = switchFactors.first {
                requested = max(requested, first * 1.001)
            }
        case .two:
            break
        case .three:
            if switchFactors.count > 1, let last = switchFactors.last {
                requested = max(requested, last * 1.001)
            }
        }

        return min(
            max(requested, device.minAvailableVideoZoomFactor),
            device.maxAvailableVideoZoomFactor
        )
    }

    private func wideBaseZoomFactor(for device: AVCaptureDevice) -> CGFloat {
        let hasUltraWide = device.constituentDevices.contains {
            $0.deviceType == .builtInUltraWideCamera
        }
        guard hasUltraWide,
              let firstSwitchFactor = device.virtualDeviceSwitchOverVideoZoomFactors.first?.doubleValue,
              firstSwitchFactor > 0 else {
            return 1
        }
        return CGFloat(firstSwitchFactor)
    }

    private func displayZoomMultiplier(for device: AVCaptureDevice?) -> CGFloat {
        guard let device else { return 1 }
        return 1 / max(wideBaseZoomFactor(for: device), 0.0001)
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
        activeLensDescription = lensName(for: activeDevice)

        if activeDevice.deviceType == .builtInWideAngleCamera,
           selectedPreset == .two {
            activeLensDescription = "Wide · 2× crop"
        }
    }

    private func lensName(for device: AVCaptureDevice) -> String {
        switch device.deviceType {
        case .builtInUltraWideCamera:
            return "Ultra Wide"
        case .builtInTelephotoCamera:
            return "Telephoto"
        case .builtInWideAngleCamera:
            return "Wide"
        default:
            return device.localizedName
        }
    }

    private func diagnostics(for device: AVCaptureDevice) -> String {
        let constituents = device.constituentDevices
            .map { $0.deviceType.rawValue }
            .joined(separator: ",")
        let switchFactors = device.virtualDeviceSwitchOverVideoZoomFactors
            .map { String(format: "%.4f", $0.doubleValue) }
            .joined(separator: ",")
        return [
            "device=\(device.deviceType.rawValue)",
            "min=\(device.minAvailableVideoZoomFactor)",
            "max=\(device.maxAvailableVideoZoomFactor)",
            "wideBase=\(wideBaseZoomFactor(for: device))",
            "switches=[\(switchFactors)]",
            "constituents=[\(constituents)]"
        ].joined(separator: " ")
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
