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

package enum HandPoseGestureClassifier {
    package static func isOpenPalm(
        wrist: GesturePoint2D?,
        fingers: [FingerGestureObservation],
        pinchDistance: Double? = nil
    ) -> Bool? {
        if let pinchDistance, pinchDistance <= 0.05 {
            return false
        }
        guard let wrist else { return nil }

        let knownExtensionStates = fingers.compactMap { finger -> Bool? in
            guard let tip = finger.tip, let base = finger.base else {
                return nil
            }
            return distance(tip, wrist) > distance(base, wrist) * 1.2
        }

        guard knownExtensionStates.count >= 3 else {
            return nil
        }

        return knownExtensionStates.filter { $0 }.count >= 3
    }

    private static func distance(_ first: GesturePoint2D, _ second: GesturePoint2D) -> Double {
        hypot(first.x - second.x, first.y - second.y)
    }
}

package struct GestureRecognitionFrame: Sendable {
    package let timestamp: TimeInterval
    package let isOpenPalm: Bool?
    package let wristX: Double?
    package let wristY: Double?
    package let pinchDistance: Double?

    package init(
        timestamp: TimeInterval,
        isOpenPalm: Bool?,
        wristX: Double?,
        wristY: Double?,
        pinchDistance: Double?
    ) {
        self.timestamp = timestamp
        self.isOpenPalm = isOpenPalm
        self.wristX = wristX
        self.wristY = wristY
        self.pinchDistance = pinchDistance
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
    private struct WristSample: Sendable {
        let timestamp: TimeInterval
        let x: Double
        let y: Double
    }

    private let pauseHoldDuration: TimeInterval = 3
    private let pauseStillnessLimit = 0.08
    private let pauseReleaseDuration: TimeInterval = 0.5
    private let openPalmLandmarkGrace: TimeInterval = 0.2
    private let waveWindow: TimeInterval = 4
    private let waveMinimumHorizontalSpan = 0.12
    private let waveNoiseGate = 0.005
    private let pinchHoldDuration: TimeInterval = 2
    private let pinchActiveThreshold = 0.05
    private let pinchReleaseThreshold = 0.07
    private let commandCooldown: TimeInterval = 2

    private var pauseSamples: [WristSample] = []
    private var pauseRequiresRelease = false
    private var pauseReleaseStartedAt: TimeInterval?
    private var lastConfirmedOpenPalmAt: TimeInterval?

    private var waveSamples: [WristSample] = []
    private var waveRequiresRelease = false

    private var pinchStartedAt: TimeInterval?
    private var pinchIsActive = false
    private var pinchRequiresSeparation = false

    private var cooldownUntil: TimeInterval = 0
    private var lastTimestamp: TimeInterval?

    package init() {}

    package mutating func reset(at timestamp: TimeInterval, initialCooldown: TimeInterval = 2) {
        pauseSamples.removeAll(keepingCapacity: true)
        pauseRequiresRelease = false
        pauseReleaseStartedAt = nil
        lastConfirmedOpenPalmAt = nil
        waveSamples.removeAll(keepingCapacity: true)
        waveRequiresRelease = false
        pinchStartedAt = nil
        pinchIsActive = false
        pinchRequiresSeparation = false
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

        let effectiveOpenPalm = resolvedOpenPalm(
            for: frame,
            enabled: settings.pauseEnabled || settings.stopEnabled
        )
        updatePauseState(
            frame,
            isOpenPalm: effectiveOpenPalm,
            enabled: settings.pauseEnabled
        )
        updateWaveState(
            frame,
            isOpenPalm: effectiveOpenPalm,
            enabled: settings.stopEnabled
        )
        updatePinchState(frame, enabled: settings.markEnabled)

        guard frame.timestamp >= cooldownUntil else { return nil }

        if settings.stopEnabled, waveIsComplete {
            waveSamples.removeAll(keepingCapacity: true)
            waveRequiresRelease = true
            pauseSamples.removeAll(keepingCapacity: true)
            cooldownUntil = frame.timestamp + commandCooldown
            return .stop
        }

        if settings.pauseEnabled, pauseIsComplete {
            pauseSamples.removeAll(keepingCapacity: true)
            pauseRequiresRelease = true
            pauseReleaseStartedAt = nil
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
            cooldownUntil = frame.timestamp + commandCooldown
            return .markSegment
        }

        return nil
    }

    private mutating func resolvedOpenPalm(
        for frame: GestureRecognitionFrame,
        enabled: Bool
    ) -> Bool? {
        guard enabled else {
            lastConfirmedOpenPalmAt = nil
            return frame.isOpenPalm
        }

        if frame.isOpenPalm == true {
            lastConfirmedOpenPalmAt = frame.timestamp
            return true
        }

        if frame.isOpenPalm == false {
            lastConfirmedOpenPalmAt = nil
            return false
        }

        guard frame.wristX != nil, frame.wristY != nil else {
            lastConfirmedOpenPalmAt = nil
            return nil
        }

        if let lastConfirmedOpenPalmAt,
           frame.timestamp - lastConfirmedOpenPalmAt <= openPalmLandmarkGrace {
            return true
        }

        return nil
    }

    private mutating func updatePauseState(
        _ frame: GestureRecognitionFrame,
        isOpenPalm: Bool?,
        enabled: Bool
    ) {
        guard enabled else {
            pauseSamples.removeAll(keepingCapacity: true)
            pauseReleaseStartedAt = nil
            pauseRequiresRelease = false
            return
        }

        guard isOpenPalm == true,
              let wristX = frame.wristX,
              let wristY = frame.wristY else {
            pauseSamples.removeAll(keepingCapacity: true)
            if pauseRequiresRelease {
                if pauseReleaseStartedAt == nil {
                    pauseReleaseStartedAt = frame.timestamp
                } else if frame.timestamp - (pauseReleaseStartedAt ?? frame.timestamp) >= pauseReleaseDuration {
                    pauseRequiresRelease = false
                    pauseReleaseStartedAt = nil
                }
            }
            return
        }

        pauseReleaseStartedAt = nil
        guard !pauseRequiresRelease else {
            pauseSamples.removeAll(keepingCapacity: true)
            return
        }

        pauseSamples.append(WristSample(timestamp: frame.timestamp, x: wristX, y: wristY))
        Self.prune(&pauseSamples, olderThan: frame.timestamp - pauseHoldDuration)

        if Self.horizontalSpan(of: pauseSamples) >= pauseStillnessLimit ||
            Self.verticalSpan(of: pauseSamples) >= pauseStillnessLimit {
            pauseSamples.removeAll(keepingCapacity: true)
            pauseSamples.append(WristSample(timestamp: frame.timestamp, x: wristX, y: wristY))
        }
    }

    private mutating func updateWaveState(
        _ frame: GestureRecognitionFrame,
        isOpenPalm: Bool?,
        enabled: Bool
    ) {
        guard enabled else {
            waveSamples.removeAll(keepingCapacity: true)
            waveRequiresRelease = false
            return
        }

        guard isOpenPalm == true,
              let wristX = frame.wristX,
              let wristY = frame.wristY else {
            waveSamples.removeAll(keepingCapacity: true)
            waveRequiresRelease = false
            return
        }

        guard !waveRequiresRelease else {
            waveSamples.removeAll(keepingCapacity: true)
            return
        }

        waveSamples.append(WristSample(timestamp: frame.timestamp, x: wristX, y: wristY))
        Self.prune(&waveSamples, olderThan: frame.timestamp - waveWindow)
    }

    private mutating func updatePinchState(_ frame: GestureRecognitionFrame, enabled: Bool) {
        guard enabled else {
            pinchStartedAt = nil
            pinchIsActive = false
            pinchRequiresSeparation = false
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

    private var pauseIsComplete: Bool {
        guard let first = pauseSamples.first,
              let last = pauseSamples.last,
              last.timestamp - first.timestamp >= pauseHoldDuration - 0.000_001 else {
            return false
        }
        return Self.horizontalSpan(of: pauseSamples) < pauseStillnessLimit &&
            Self.verticalSpan(of: pauseSamples) < pauseStillnessLimit
    }

    private var waveIsComplete: Bool {
        guard Self.horizontalSpan(of: waveSamples) >= waveMinimumHorizontalSpan else {
            return false
        }

        var directionChanges = 0
        var lastDirection = 0

        for index in 1..<waveSamples.count {
            let delta = waveSamples[index].x - waveSamples[index - 1].x
            guard abs(delta) > waveNoiseGate else { continue }
            let direction = delta > 0 ? 1 : -1
            if lastDirection != 0, direction != lastDirection {
                directionChanges += 1
            }
            lastDirection = direction
        }

        return directionChanges >= 3
    }

    private static func horizontalSpan(of samples: [WristSample]) -> Double {
        guard let minimum = samples.map(\.x).min(),
              let maximum = samples.map(\.x).max() else {
            return 0
        }
        return maximum - minimum
    }

    private static func verticalSpan(of samples: [WristSample]) -> Double {
        guard let minimum = samples.map(\.y).min(),
              let maximum = samples.map(\.y).max() else {
            return 0
        }
        return maximum - minimum
    }

    private static func prune(_ samples: inout [WristSample], olderThan cutoff: TimeInterval) {
        while let first = samples.first, first.timestamp < cutoff - 0.000_001 {
            samples.removeFirst()
        }
    }
}
