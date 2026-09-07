import Foundation

package enum UIGestureCommand: Sendable, Equatable {
    case start
    case stop
    case pause
    case resume
    case markSegment
}

package struct GesturePoint2D: Sendable, Equatable {
    package let x: Double
    package let y: Double

    package init(x: Double, y: Double) {
        self.x = x
        self.y = y
    }
}

package struct FingerGestureObservation: Sendable, Equatable {
    package let tip: GesturePoint2D?
    package let base: GesturePoint2D?

    package init(tip: GesturePoint2D?, base: GesturePoint2D?) {
        self.tip = tip
        self.base = base
    }
}

package struct GestureLuminanceStatistics: Sendable, Equatable {
    package let mean: Double
    package let standardDeviation: Double

    package init(mean: Double, standardDeviation: Double) {
        self.mean = mean
        self.standardDeviation = standardDeviation
    }
}

package enum HandPoseGestureClassifier {
    package static func isYoGesture(
        wrist: GesturePoint2D?,
        thumb: FingerGestureObservation,
        index: FingerGestureObservation,
        middle: FingerGestureObservation,
        ring: FingerGestureObservation,
        little: FingerGestureObservation,
        pinchDistance: Double?
    ) -> Bool? {
        if let pinchDistance, pinchDistance <= 0.07 {
            return false
        }
        guard let wrist else { return nil }

        let thumbExtended = extensionState(
            wrist: wrist,
            finger: thumb,
            extensionMultiplier: 1.15
        )
        let indexExtended = extensionState(wrist: wrist, finger: index)
        let middleExtended = extensionState(wrist: wrist, finger: middle)
        let ringExtended = extensionState(wrist: wrist, finger: ring)
        let littleExtended = extensionState(wrist: wrist, finger: little)

        let requiredExtended = [thumbExtended, indexExtended, littleExtended]
        if requiredExtended.contains(where: { $0 == false }) {
            return false
        }
        guard requiredExtended.allSatisfy({ $0 != nil }) else {
            return nil
        }

        let foldedFingers = [middleExtended, ringExtended]
        if foldedFingers.contains(where: { $0 == true }) {
            return false
        }
        guard foldedFingers.contains(where: { $0 == false }) else {
            return nil
        }

        return true
    }

    private static func extensionState(
        wrist: GesturePoint2D,
        finger: FingerGestureObservation,
        extensionMultiplier: Double = 1.2
    ) -> Bool? {
        guard let tip = finger.tip, let base = finger.base else {
            return nil
        }

        let baseDistance = distance(base, wrist)
        guard baseDistance > 0.000_001 else { return nil }
        return distance(tip, wrist) > baseDistance * extensionMultiplier
    }

    private static func distance(_ first: GesturePoint2D, _ second: GesturePoint2D) -> Double {
        hypot(first.x - second.x, first.y - second.y)
    }
}

package struct GestureRecognitionFrame: Sendable {
    package let timestamp: TimeInterval
    package let isYoGesture: Bool?
    package let hasTrackedWrist: Bool
    package let pinchDistance: Double?
    package let luminance: GestureLuminanceStatistics?

    package init(
        timestamp: TimeInterval,
        isYoGesture: Bool?,
        hasTrackedWrist: Bool,
        pinchDistance: Double?,
        luminance: GestureLuminanceStatistics?
    ) {
        self.timestamp = timestamp
        self.isYoGesture = isYoGesture
        self.hasTrackedWrist = hasTrackedWrist
        self.pinchDistance = pinchDistance
        self.luminance = luminance
    }
}

package struct GestureRecognitionSettings: Sendable {
    package let pauseEnabled: Bool
    package let stopEnabled: Bool
    package let markEnabled: Bool

    package init(pauseEnabled: Bool, stopEnabled: Bool, markEnabled: Bool) {
        self.pauseEnabled = pauseEnabled
        self.stopEnabled = stopEnabled
        self.markEnabled = markEnabled
    }
}

package struct GestureRecognitionStateMachine: Sendable {
    private let yoHoldDuration: TimeInterval = 2
    private let yoReleaseDuration: TimeInterval = 0.5
    private let yoLandmarkGrace: TimeInterval = 0.2

    private let coverCalibrationDuration: TimeInterval = 1
    private let coverHoldDuration: TimeInterval = 3
    private let coverReleaseDuration: TimeInterval = 0.5
    private let coverAbsoluteMeanLimit = 0.12
    private let coverBaselineFraction = 0.35
    private let coverDeviationLimit = 0.08
    private let coverBaselineAlpha = 0.05

    private let pinchHoldDuration: TimeInterval = 2
    private let pinchActiveThreshold = 0.05
    private let pinchReleaseThreshold = 0.07
    private let commandCooldown: TimeInterval = 2

    private var yoStartedAt: TimeInterval?
    private var yoRequiresRelease = false
    private var yoReleaseStartedAt: TimeInterval?
    private var lastConfirmedYoAt: TimeInterval?

    private var coverBaselineMean: Double?
    private var coverCalibrationStartedAt: TimeInterval?
    private var coverBaselineIsReady = false
    private var coverStartedAt: TimeInterval?
    private var coverRequiresRelease = false
    private var coverReleaseStartedAt: TimeInterval?

    private var pinchStartedAt: TimeInterval?
    private var pinchIsActive = false
    private var pinchRequiresSeparation = false

    private var cooldownUntil: TimeInterval = 0
    private var lastTimestamp: TimeInterval?

    package init() {}

    package mutating func reset(at timestamp: TimeInterval, initialCooldown: TimeInterval = 2) {
        clearYoState()
        clearCoverState()
        clearPinchState()
        cooldownUntil = timestamp + initialCooldown
        lastTimestamp = timestamp
    }

    package mutating func process(
        _ frame: GestureRecognitionFrame,
        settings: GestureRecognitionSettings
    ) -> UIGestureCommand? {
        if let lastTimestamp, frame.timestamp < lastTimestamp {
            reset(at: frame.timestamp, initialCooldown: 0)
        }
        lastTimestamp = frame.timestamp

        let effectiveYo = resolvedYoGesture(for: frame, enabled: settings.pauseEnabled)
        updateYoState(frame, isYoGesture: effectiveYo, enabled: settings.pauseEnabled)
        updateCoverState(frame, enabled: settings.stopEnabled)
        updatePinchState(frame, enabled: settings.markEnabled)

        guard frame.timestamp >= cooldownUntil else { return nil }

        if settings.stopEnabled, coverIsComplete(at: frame.timestamp) {
            coverStartedAt = nil
            coverRequiresRelease = true
            coverReleaseStartedAt = nil
            yoStartedAt = nil
            pinchStartedAt = nil
            pinchIsActive = false
            cooldownUntil = frame.timestamp + commandCooldown
            return .stop
        }

        if settings.pauseEnabled, yoIsComplete(at: frame.timestamp) {
            yoStartedAt = nil
            yoRequiresRelease = true
            yoReleaseStartedAt = nil
            pinchStartedAt = nil
            pinchIsActive = false
            cooldownUntil = frame.timestamp + commandCooldown
            return .pause
        }

        if settings.markEnabled,
           pinchIsActive,
           !pinchRequiresSeparation,
           let pinchStartedAt,
           frame.timestamp - pinchStartedAt >= pinchHoldDuration {
            self.pinchStartedAt = nil
            pinchRequiresSeparation = true
            yoStartedAt = nil
            cooldownUntil = frame.timestamp + commandCooldown
            return .markSegment
        }

        return nil
    }

    private mutating func resolvedYoGesture(
        for frame: GestureRecognitionFrame,
        enabled: Bool
    ) -> Bool? {
        guard enabled else {
            lastConfirmedYoAt = nil
            return frame.isYoGesture
        }

        if frame.isYoGesture == true {
            lastConfirmedYoAt = frame.timestamp
            return true
        }

        if frame.isYoGesture == false {
            lastConfirmedYoAt = nil
            return false
        }

        guard frame.hasTrackedWrist else {
            lastConfirmedYoAt = nil
            return nil
        }

        if let lastConfirmedYoAt,
           frame.timestamp - lastConfirmedYoAt <= yoLandmarkGrace {
            return true
        }

        return nil
    }

    private mutating func updateYoState(
        _ frame: GestureRecognitionFrame,
        isYoGesture: Bool?,
        enabled: Bool
    ) {
        guard enabled else {
            clearYoState()
            return
        }

        guard isYoGesture == true else {
            yoStartedAt = nil
            if yoRequiresRelease {
                if yoReleaseStartedAt == nil {
                    yoReleaseStartedAt = frame.timestamp
                } else if frame.timestamp - (yoReleaseStartedAt ?? frame.timestamp) >= yoReleaseDuration {
                    yoRequiresRelease = false
                    yoReleaseStartedAt = nil
                }
            }
            return
        }

        yoReleaseStartedAt = nil
        guard !yoRequiresRelease else { return }
        if yoStartedAt == nil {
            yoStartedAt = frame.timestamp
        }
    }

    private mutating func updateCoverState(
        _ frame: GestureRecognitionFrame,
        enabled: Bool
    ) {
        guard enabled else {
            clearCoverState()
            return
        }

        guard let statistics = frame.luminance,
              statistics.mean.isFinite,
              statistics.standardDeviation.isFinite else {
            coverStartedAt = nil
            return
        }

        let mean = min(max(statistics.mean, 0), 1)
        let deviation = min(max(statistics.standardDeviation, 0), 1)

        guard coverBaselineIsReady else {
            if coverCalibrationStartedAt == nil {
                coverCalibrationStartedAt = frame.timestamp
                coverBaselineMean = mean
            } else {
                coverBaselineMean = blendedBaseline(current: coverBaselineMean ?? mean, sample: mean, alpha: 0.2)
            }

            if frame.timestamp - (coverCalibrationStartedAt ?? frame.timestamp) >= coverCalibrationDuration {
                coverBaselineIsReady = true
            }
            coverStartedAt = nil
            return
        }

        let baseline = coverBaselineMean ?? mean
        let meanLimit = min(coverAbsoluteMeanLimit, baseline * coverBaselineFraction)
        let isCovered = mean <= meanLimit && deviation <= coverDeviationLimit

        if isCovered {
            coverReleaseStartedAt = nil
            guard !coverRequiresRelease else {
                coverStartedAt = nil
                return
            }
            if coverStartedAt == nil {
                coverStartedAt = frame.timestamp
            }
            return
        }

        coverStartedAt = nil

        if coverRequiresRelease {
            if coverReleaseStartedAt == nil {
                coverReleaseStartedAt = frame.timestamp
            } else if frame.timestamp - (coverReleaseStartedAt ?? frame.timestamp) >= coverReleaseDuration {
                coverRequiresRelease = false
                coverReleaseStartedAt = nil
            }
            return
        }

        coverBaselineMean = blendedBaseline(
            current: baseline,
            sample: mean,
            alpha: coverBaselineAlpha
        )
    }

    private mutating func updatePinchState(_ frame: GestureRecognitionFrame, enabled: Bool) {
        guard enabled else {
            clearPinchState()
            return
        }

        guard let distance = frame.pinchDistance else {
            pinchStartedAt = nil
            pinchIsActive = false
            return
        }

        if pinchIsActive {
            if distance >= pinchReleaseThreshold {
                pinchIsActive = false
                pinchStartedAt = nil
                pinchRequiresSeparation = false
            }
        } else if distance <= pinchActiveThreshold {
            pinchIsActive = true
            if !pinchRequiresSeparation {
                pinchStartedAt = frame.timestamp
            }
        } else if distance >= pinchReleaseThreshold {
            pinchRequiresSeparation = false
        }
    }

    private func yoIsComplete(at timestamp: TimeInterval) -> Bool {
        guard let yoStartedAt else { return false }
        return timestamp - yoStartedAt >= yoHoldDuration
    }

    private func coverIsComplete(at timestamp: TimeInterval) -> Bool {
        guard let coverStartedAt else { return false }
        return timestamp - coverStartedAt >= coverHoldDuration
    }

    private func blendedBaseline(
        current: Double,
        sample: Double,
        alpha: Double
    ) -> Double {
        current + (sample - current) * alpha
    }

    private mutating func clearYoState() {
        yoStartedAt = nil
        yoRequiresRelease = false
        yoReleaseStartedAt = nil
        lastConfirmedYoAt = nil
    }

    private mutating func clearCoverState() {
        coverBaselineMean = nil
        coverCalibrationStartedAt = nil
        coverBaselineIsReady = false
        coverStartedAt = nil
        coverRequiresRelease = false
        coverReleaseStartedAt = nil
    }

    private mutating func clearPinchState() {
        pinchStartedAt = nil
        pinchIsActive = false
        pinchRequiresSeparation = false
    }
}
