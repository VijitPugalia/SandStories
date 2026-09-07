import XCTest
@testable import GestureRecognition

final class GestureRecognitionStateMachineTests: XCTestCase {
    private let frameRates = [8, 15, 30]

    func testYoHoldFiresOnceAndRequiresRelease() {
        for frameRate in frameRates {
            var machine = GestureRecognitionStateMachine()
            machine.reset(at: 0, initialCooldown: 0)
            var time: TimeInterval = 0
            let pauseOnly = GestureRecognitionSettings(
                pauseEnabled: true,
                stopEnabled: false,
                markEnabled: false
            )

            var commands = feed(
                machine: &machine,
                time: &time,
                duration: 1.8,
                frameRate: frameRate,
                settings: pauseOnly
            ) { .yo(timestamp: $0) }
            XCTAssertTrue(commands.isEmpty, "Short Yo hold fired at \(frameRate) fps")

            commands += feed(
                machine: &machine,
                time: &time,
                duration: 0.3,
                frameRate: frameRate,
                settings: pauseOnly
            ) { .released(timestamp: $0) }

            commands += feed(
                machine: &machine,
                time: &time,
                duration: 2.2,
                frameRate: frameRate,
                settings: pauseOnly
            ) { .yo(timestamp: $0) }
            XCTAssertEqual(commands, [.pause], "Yo hold failed at \(frameRate) fps")

            commands += feed(
                machine: &machine,
                time: &time,
                duration: 3,
                frameRate: frameRate,
                settings: pauseOnly
            ) { .yo(timestamp: $0) }
            XCTAssertEqual(commands, [.pause], "Held Yo gesture duplicated at \(frameRate) fps")

            _ = feed(
                machine: &machine,
                time: &time,
                duration: 0.6,
                frameRate: frameRate,
                settings: pauseOnly
            ) { .released(timestamp: $0) }

            commands += feed(
                machine: &machine,
                time: &time,
                duration: 2.2,
                frameRate: frameRate,
                settings: pauseOnly
            ) { .yo(timestamp: $0) }
            XCTAssertEqual(
                commands,
                [.pause, .pause],
                "Yo gesture did not rearm at \(frameRate) fps"
            )
        }
    }

    func testYoLandmarkGraceAndHandLoss() {
        for frameRate in frameRates {
            let pauseOnly = GestureRecognitionSettings(
                pauseEnabled: true,
                stopEnabled: false,
                markEnabled: false
            )
            var machine = GestureRecognitionStateMachine()
            machine.reset(at: 0, initialCooldown: 0)
            var time: TimeInterval = 0

            var commands = feed(
                machine: &machine,
                time: &time,
                duration: 1.05,
                frameRate: frameRate,
                settings: pauseOnly
            ) { .yo(timestamp: $0) }
            commands += feed(
                machine: &machine,
                time: &time,
                duration: 0,
                frameRate: frameRate,
                settings: pauseOnly
            ) { .unknownYo(timestamp: $0, wristTracked: true) }
            commands += feed(
                machine: &machine,
                time: &time,
                duration: 1.05,
                frameRate: frameRate,
                settings: pauseOnly
            ) { .yo(timestamp: $0) }
            XCTAssertEqual(
                commands,
                [.pause],
                "Brief landmark gap broke Yo hold at \(frameRate) fps"
            )

            machine.reset(at: 0, initialCooldown: 0)
            time = 0
            commands = feed(
                machine: &machine,
                time: &time,
                duration: 1.2,
                frameRate: frameRate,
                settings: pauseOnly
            ) { .yo(timestamp: $0) }
            _ = feed(
                machine: &machine,
                time: &time,
                duration: 0.3,
                frameRate: frameRate,
                settings: pauseOnly
            ) { .unknownYo(timestamp: $0, wristTracked: false) }
            commands += feed(
                machine: &machine,
                time: &time,
                duration: 1.2,
                frameRate: frameRate,
                settings: pauseOnly
            ) { .yo(timestamp: $0) }
            XCTAssertTrue(
                commands.isEmpty,
                "Yo hold survived hand loss at \(frameRate) fps"
            )
        }
    }

    func testYoClassifierAcceptsRequestedPoseAndRejectsConflicts() {
        let wrist = GesturePoint2D(x: 0.5, y: 0.2)
        let thumb = extendedFinger(baseX: 0.43, tipX: 0.2)
        let index = extendedFinger(baseX: 0.46, tipX: 0.42)
        let middle = foldedFinger(x: 0.49)
        let ring = foldedFinger(x: 0.54)
        let little = extendedFinger(baseX: 0.58, tipX: 0.68)

        XCTAssertEqual(
            HandPoseGestureClassifier.isYoGesture(
                wrist: wrist,
                thumb: thumb,
                index: index,
                middle: middle,
                ring: ring,
                little: little,
                pinchDistance: 0.2
            ),
            true
        )

        XCTAssertEqual(
            HandPoseGestureClassifier.isYoGesture(
                wrist: wrist,
                thumb: thumb,
                index: index,
                middle: middle,
                ring: ring,
                little: little,
                pinchDistance: 0.03
            ),
            false,
            "Active pinch must not also classify as Yo"
        )

        XCTAssertEqual(
            HandPoseGestureClassifier.isYoGesture(
                wrist: wrist,
                thumb: thumb,
                index: index,
                middle: extendedFinger(baseX: 0.49, tipX: 0.49),
                ring: ring,
                little: little,
                pinchDistance: 0.2
            ),
            false,
            "Extended middle finger must reject Yo"
        )

        XCTAssertEqual(
            HandPoseGestureClassifier.isYoGesture(
                wrist: wrist,
                thumb: thumb,
                index: index,
                middle: .init(tip: nil, base: nil),
                ring: ring,
                little: little,
                pinchDistance: 0.2
            ),
            true,
            "One missing folded finger should be tolerated"
        )

        XCTAssertNil(
            HandPoseGestureClassifier.isYoGesture(
                wrist: wrist,
                thumb: thumb,
                index: index,
                middle: middle,
                ring: ring,
                little: .init(tip: nil, base: nil),
                pinchDistance: 0.2
            ),
            "A required extended finger must not be guessed"
        )
    }

    func testCameraCoverStopsOnceAndRearms() {
        for frameRate in frameRates {
            var machine = GestureRecognitionStateMachine()
            machine.reset(at: 0, initialCooldown: 0)
            var time: TimeInterval = 0
            let stopOnly = GestureRecognitionSettings(
                pauseEnabled: false,
                stopEnabled: true,
                markEnabled: false
            )

            var commands = feed(
                machine: &machine,
                time: &time,
                duration: 1.2,
                frameRate: frameRate,
                settings: stopOnly
            ) { .luminance(timestamp: $0, mean: 0.55, deviation: 0.18) }
            commands += feed(
                machine: &machine,
                time: &time,
                duration: 3.2,
                frameRate: frameRate,
                settings: stopOnly
            ) { .luminance(timestamp: $0, mean: 0.02, deviation: 0.01) }
            XCTAssertEqual(commands, [.stop], "Camera cover failed at \(frameRate) fps")

            commands += feed(
                machine: &machine,
                time: &time,
                duration: 2,
                frameRate: frameRate,
                settings: stopOnly
            ) { .luminance(timestamp: $0, mean: 0.02, deviation: 0.01) }
            XCTAssertEqual(commands, [.stop], "Continued cover duplicated Stop at \(frameRate) fps")

            _ = feed(
                machine: &machine,
                time: &time,
                duration: 0.6,
                frameRate: frameRate,
                settings: stopOnly
            ) { .luminance(timestamp: $0, mean: 0.55, deviation: 0.18) }
            commands += feed(
                machine: &machine,
                time: &time,
                duration: 3.2,
                frameRate: frameRate,
                settings: stopOnly
            ) { .luminance(timestamp: $0, mean: 0.02, deviation: 0.01) }
            XCTAssertEqual(commands, [.stop, .stop], "Camera cover did not rearm at \(frameRate) fps")
        }
    }

    func testShortCoverShadowsAndTexturedDarkFramesDoNotStop() {
        for frameRate in frameRates {
            var machine = GestureRecognitionStateMachine()
            machine.reset(at: 0, initialCooldown: 0)
            var time: TimeInterval = 0
            let stopOnly = GestureRecognitionSettings(
                pauseEnabled: false,
                stopEnabled: true,
                markEnabled: false
            )

            var commands = feed(
                machine: &machine,
                time: &time,
                duration: 1.2,
                frameRate: frameRate,
                settings: stopOnly
            ) { .luminance(timestamp: $0, mean: 0.55, deviation: 0.18) }

            commands += feed(
                machine: &machine,
                time: &time,
                duration: 2.8,
                frameRate: frameRate,
                settings: stopOnly
            ) { .luminance(timestamp: $0, mean: 0.02, deviation: 0.01) }
            XCTAssertTrue(commands.isEmpty, "Short cover stopped at \(frameRate) fps")

            _ = feed(
                machine: &machine,
                time: &time,
                duration: 0.3,
                frameRate: frameRate,
                settings: stopOnly
            ) { .luminance(timestamp: $0, mean: 0.55, deviation: 0.18) }

            commands += feed(
                machine: &machine,
                time: &time,
                duration: 3.2,
                frameRate: frameRate,
                settings: stopOnly
            ) { .luminance(timestamp: $0, mean: 0.2, deviation: 0.03) }
            XCTAssertTrue(commands.isEmpty, "Ordinary shadow stopped at \(frameRate) fps")

            commands += feed(
                machine: &machine,
                time: &time,
                duration: 3.2,
                frameRate: frameRate,
                settings: stopOnly
            ) { .luminance(timestamp: $0, mean: 0.03, deviation: 0.12) }
            XCTAssertTrue(commands.isEmpty, "Textured dark frame stopped at \(frameRate) fps")
        }
    }

    func testPinchHoldMarksOnceAndRequiresSeparation() {
        for frameRate in frameRates {
            var machine = GestureRecognitionStateMachine()
            machine.reset(at: 0, initialCooldown: 0)
            var time: TimeInterval = 0
            let markOnly = GestureRecognitionSettings(
                pauseEnabled: false,
                stopEnabled: false,
                markEnabled: true
            )

            var commands = feed(
                machine: &machine,
                time: &time,
                duration: 1.8,
                frameRate: frameRate,
                settings: markOnly
            ) { .pinch(timestamp: $0, distance: 0.03) }
            XCTAssertTrue(commands.isEmpty, "Short pinch fired at \(frameRate) fps")

            _ = feed(
                machine: &machine,
                time: &time,
                duration: 0.2,
                frameRate: frameRate,
                settings: markOnly
            ) { .pinch(timestamp: $0, distance: 0.08) }

            commands += feed(
                machine: &machine,
                time: &time,
                duration: 2.2,
                frameRate: frameRate,
                settings: markOnly
            ) { .pinch(timestamp: $0, distance: 0.03) }
            XCTAssertEqual(commands, [.markSegment], "Pinch hold failed at \(frameRate) fps")

            commands += feed(
                machine: &machine,
                time: &time,
                duration: 3,
                frameRate: frameRate,
                settings: markOnly
            ) { .pinch(timestamp: $0, distance: 0.03) }
            XCTAssertEqual(commands, [.markSegment], "Held pinch duplicated at \(frameRate) fps")

            _ = feed(
                machine: &machine,
                time: &time,
                duration: 0.2,
                frameRate: frameRate,
                settings: markOnly
            ) { .pinch(timestamp: $0, distance: 0.08) }

            commands += feed(
                machine: &machine,
                time: &time,
                duration: 2.2,
                frameRate: frameRate,
                settings: markOnly
            ) { .pinch(timestamp: $0, distance: 0.03) }
            XCTAssertEqual(
                commands,
                [.markSegment, .markSegment],
                "Pinch did not rearm at \(frameRate) fps"
            )
        }
    }

    func testDisabledGesturesClearPartialState() {
        for frameRate in frameRates {
            var machine = GestureRecognitionStateMachine()
            machine.reset(at: 0, initialCooldown: 0)
            var time: TimeInterval = 0
            let disabled = GestureRecognitionSettings(
                pauseEnabled: false,
                stopEnabled: false,
                markEnabled: false
            )
            let pauseOnly = GestureRecognitionSettings(
                pauseEnabled: true,
                stopEnabled: false,
                markEnabled: false
            )

            var commands = feed(
                machine: &machine,
                time: &time,
                duration: 2.2,
                frameRate: frameRate,
                settings: disabled
            ) { .yo(timestamp: $0) }
            XCTAssertTrue(commands.isEmpty)

            commands += feed(
                machine: &machine,
                time: &time,
                duration: 1.8,
                frameRate: frameRate,
                settings: pauseOnly
            ) { .yo(timestamp: $0) }
            XCTAssertTrue(commands.isEmpty, "Disabled Yo time carried over at \(frameRate) fps")

            commands += feed(
                machine: &machine,
                time: &time,
                duration: 0.4,
                frameRate: frameRate,
                settings: pauseOnly
            ) { .yo(timestamp: $0) }
            XCTAssertEqual(commands, [.pause], "Fresh enabled Yo hold failed at \(frameRate) fps")
        }
    }

    func testTimestampRollbackClearsPartialRecognition() {
        var machine = GestureRecognitionStateMachine()
        machine.reset(at: 10, initialCooldown: 0)
        let pauseOnly = GestureRecognitionSettings(
            pauseEnabled: true,
            stopEnabled: false,
            markEnabled: false
        )

        XCTAssertNil(machine.process(.yo(timestamp: 10), settings: pauseOnly))
        XCTAssertNil(machine.process(.yo(timestamp: 11.5), settings: pauseOnly))
        XCTAssertNil(machine.process(.yo(timestamp: 1), settings: pauseOnly))
        XCTAssertNil(machine.process(.yo(timestamp: 2.5), settings: pauseOnly))
        XCTAssertEqual(machine.process(.yo(timestamp: 3.1), settings: pauseOnly), .pause)
    }

    private func extendedFinger(baseX: Double, tipX: Double) -> FingerGestureObservation {
        FingerGestureObservation(
            tip: GesturePoint2D(x: tipX, y: 0.72),
            base: GesturePoint2D(x: baseX, y: 0.36)
        )
    }

    private func foldedFinger(x: Double) -> FingerGestureObservation {
        FingerGestureObservation(
            tip: GesturePoint2D(x: x + 0.01, y: 0.38),
            base: GesturePoint2D(x: x, y: 0.36)
        )
    }

    private func feed(
        machine: inout GestureRecognitionStateMachine,
        time: inout TimeInterval,
        duration: TimeInterval,
        frameRate: Int,
        settings: GestureRecognitionSettings,
        frame: (TimeInterval) -> GestureRecognitionFrame
    ) -> [UIGestureCommand] {
        var commands: [UIGestureCommand] = []
        let step = 1.0 / Double(frameRate)
        let frameCount = Int(ceil(duration * Double(frameRate)))

        for _ in 0...frameCount {
            if let command = machine.process(frame(time), settings: settings) {
                commands.append(command)
            }
            time += step
        }
        return commands
    }
}

private extension GestureRecognitionFrame {
    static func yo(timestamp: TimeInterval) -> Self {
        Self(
            timestamp: timestamp,
            isYoGesture: true,
            hasTrackedWrist: true,
            pinchDistance: 0.2,
            luminance: .init(mean: 0.55, standardDeviation: 0.18)
        )
    }

    static func released(timestamp: TimeInterval) -> Self {
        Self(
            timestamp: timestamp,
            isYoGesture: false,
            hasTrackedWrist: true,
            pinchDistance: 0.2,
            luminance: .init(mean: 0.55, standardDeviation: 0.18)
        )
    }

    static func unknownYo(timestamp: TimeInterval, wristTracked: Bool) -> Self {
        Self(
            timestamp: timestamp,
            isYoGesture: nil,
            hasTrackedWrist: wristTracked,
            pinchDistance: nil,
            luminance: .init(mean: 0.55, standardDeviation: 0.18)
        )
    }

    static func pinch(timestamp: TimeInterval, distance: Double) -> Self {
        Self(
            timestamp: timestamp,
            isYoGesture: false,
            hasTrackedWrist: true,
            pinchDistance: distance,
            luminance: .init(mean: 0.55, standardDeviation: 0.18)
        )
    }

    static func luminance(
        timestamp: TimeInterval,
        mean: Double,
        deviation: Double
    ) -> Self {
        Self(
            timestamp: timestamp,
            isYoGesture: nil,
            hasTrackedWrist: false,
            pinchDistance: nil,
            luminance: .init(mean: mean, standardDeviation: deviation)
        )
    }
}
