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
    @Published private(set) var lastAppliedSummary = "1× • waiting for AR camera"

    private var captureDevice: AVCaptureDevice?
    private var lensMonitorTask: Task<Void, Never>?
    private var postSessionReapplyTask: Task<Void, Never>?
    private var requestedDeviceZoomFactor: CGFloat = 1
    private var isApplyingZoom = false
    private let logger = Logger(
        subsystem: Bundle.main.bundleIdentifier ?? "SandStories",
        category: "CameraZoom"
    )

    deinit {
        lensMonitorTask?.cancel()
        postSessionReapplyTask?.cancel()
    }

    func prepareForARSession() {
        guard let device = ARWorldTrackingConfiguration.configurableCaptureDeviceForPrimaryCamera else {
            captureDevice = nil
            supportedPresets = [.one]
            activeLensDescription = "ARKit camera unavailable"
            diagnosticSummary = "configurableCaptureDeviceForPrimaryCamera returned nil"
            lastAppliedSummary = "\(selectedPreset.title) • AR camera unavailable"
            emit(diagnosticSummary, isError: true)
            return
        }

        captureDevice = device
        supportedPresets = Set(ZoomPreset.allCases)
        diagnosticSummary = diagnostics(for: device)
        emit("prepared \(diagnosticSummary)")
        apply(preset: selectedPreset, reason: "before AR session")
        startLensMonitoring()
    }

    /// ARKit can restore capture defaults while its pipeline starts. Reapply after
    /// startup so the visible RealityKit backdrop receives the selected zoom.
    func reapplyAfterARSessionStart() {
        postSessionReapplyTask?.cancel()
        postSessionReapplyTask = Task { [weak self] in
            for delay in [150, 500, 1_200] {
                try? await Task.sleep(for: .milliseconds(delay))
                guard !Task.isCancelled, let self else { return }
                self.reapplyIfNeeded(reason: "after AR session +\(delay)ms")
            }
        }
    }

    func select(_ preset: ZoomPreset) {
        guard supportedPresets.contains(preset) else { return }
        selectedPreset = preset

        if captureDevice == nil {
            prepareForARSession()
        } else {
            apply(preset: preset, reason: "button tap")
        }

        // A short retry catches a capture-pipeline update racing the button tap.
        Task { [weak self] in
            try? await Task.sleep(for: .milliseconds(250))
            self?.reapplyIfNeeded(reason: "button settle")
        }
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

    private func apply(preset: ZoomPreset, reason: String) {
        guard !isApplyingZoom else { return }
        guard let device = captureDevice
                ?? ARWorldTrackingConfiguration.configurableCaptureDeviceForPrimaryCamera else {
            activeLensDescription = "ARKit camera unavailable"
            lastAppliedSummary = "\(preset.title) • AR camera unavailable"
            emit("zoom \(preset.title): no configurable ARKit camera", isError: true)
            return
        }
        captureDevice = device

        let beforeFactor = device.videoZoomFactor
        let beforeLens = lensName(for: device.activePrimaryConstituent ?? device)
        let targetFactor = targetDeviceZoomFactor(for: preset, device: device)
        requestedDeviceZoomFactor = targetFactor
        isApplyingZoom = true
        defer { isApplyingZoom = false }

        do {
            try device.lockForConfiguration()
            defer { device.unlockForConfiguration() }

            if device.primaryConstituentDeviceSwitchingBehavior != .unsupported {
                // Restrict scene-driven fallback while still permitting switching
                // when the requested video zoom crosses a hardware threshold.
                device.setPrimaryConstituentDeviceSwitchingBehavior(
                    .restricted,
                    restrictedSwitchingBehaviorConditions: []
                )
            }
            device.cancelVideoZoomRamp()
            device.videoZoomFactor = targetFactor
            currentDeviceZoomFactor = device.videoZoomFactor
        } catch {
            activeLensDescription = "Zoom unavailable"
            lastAppliedSummary = "\(preset.title) • configuration failed"
            emit(
                "zoom \(preset.title) failed (\(reason)): \(error.localizedDescription)",
                isError: true
            )
            return
        }

        refreshActiveLens()
        updateAppliedSummary()
        emit(
            "zoom \(preset.title) reason=\(reason) before=\(format(beforeFactor)) " +
            "target=\(format(targetFactor)) applied=\(format(currentDeviceZoomFactor)) " +
            "beforeLens=\(beforeLens) active=\(activeLensDescription)"
        )
    }

    private func reapplyIfNeeded(reason: String) {
        guard let device = captureDevice else {
            prepareForARSession()
            return
        }

        refreshActiveLens()
        let tolerance: CGFloat = 0.02
        if abs(device.videoZoomFactor - requestedDeviceZoomFactor) > tolerance {
            emit(
                "ARKit reset zoom requested=\(format(requestedDeviceZoomFactor)) " +
                "actual=\(format(device.videoZoomFactor)); reapplying"
            )
            apply(preset: selectedPreset, reason: reason)
        } else {
            updateAppliedSummary()
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
                try? await Task.sleep(for: .seconds(1))
                guard !Task.isCancelled, let self else { return }
                self.reapplyIfNeeded(reason: "ARKit reset monitor")
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

    private func updateAppliedSummary() {
        lastAppliedSummary =
            "\(selectedPreset.title) • \(activeLensDescription) • hw \(format(currentDeviceZoomFactor))×"
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
            "min=\(format(device.minAvailableVideoZoomFactor))",
            "max=\(format(device.maxAvailableVideoZoomFactor))",
            "wideBase=\(format(wideBaseZoomFactor(for: device)))",
            "switches=[\(switchFactors)]",
            "constituents=[\(constituents)]"
        ].joined(separator: " ")
    }

    private func format(_ value: CGFloat) -> String {
        String(format: "%.2f", Double(value))
    }

    private func emit(_ message: String, isError: Bool = false) {
        if isError {
            logger.error("\(message, privacy: .public)")
        } else {
            logger.notice("\(message, privacy: .public)")
        }
        print("[CameraZoom] \(message)")
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
