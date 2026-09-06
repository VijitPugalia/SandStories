import XCTest
@testable import GestureRecognition

final class GestureRecognitionStateMachineTests: XCTestCase {
    private let frameRates = [8, 15, 30]

    func testOpenPalmUsesElapsedTimeAndRequiresReleaseToRearm() {
        for frameRate in frameRates {
            var machine = GestureRecognitionStateMachine()
            machine.reset(at: 0, initialCooldown: 0)
            var time: TimeInterval = 0
            let enabled = GestureRecognitionSettings(
                pauseEnabled: true,
                stopEnabled: false,
                markEnabled: false
            )

            var commands = feed(
                machine: &machine,
                time: &time,
                duration: 2.8,
                frameRate: frameRate,
                settings: enabled
            ) { timestamp in
                .openPalm(timestamp: timestamp, x: 0.5, y: 0.5)
            }
            XCTAssertTrue(commands.isEmpty, "Short palm hold fired at \(frameRate) fps")

            commands += feed(
                machine: &machine,
                time: &time,
                duration: 0.4,
                frameRate: frameRate,
                settings: enabled
            ) { timestamp in
                .openPalm(timestamp: timestamp, x: 0.5, y: 0.5)
            }
            XCTAssertEqual(commands, [.pause], "Palm did not fire once at \(frameRate) fps")

            commands += feed(
                machine: &machine,
                time: &time,
                duration: 3.0,
                frameRate: frameRate,
                settings: enabled
            ) { timestamp in
                .openPalm(timestamp: timestamp, x: 0.5, y: 0.5)
            }
            XCTAssertEqual(commands, [.pause], "Held palm fired twice at \(frameRate) fps")

            _ = feed(
                machine: &machine,
                time: &time,
                duration: 0.6,
                frameRate: frameRate,
                settings: enabled
            ) { timestamp in
                .empty(timestamp: timestamp)
            }

            commands += feed(
                machine: &machine,
                time: &time,
                duration: 3.2,
                frameRate: frameRate,
                settings: enabled
            ) { timestamp in
                .openPalm(timestamp: timestamp, x: 0.5, y: 0.5)
            }
            XCTAssertEqual(commands, [.pause, .pause], "Palm did not rearm after release at \(frameRate) fps")
        }
    }

    func testWaveNeedsThreeQualifiedDirectionChangesAndRejectsNoise() {
        for frameRate in frameRates {
            let stopOnly = GestureRecognitionSettings(
                pauseEnabled: false,
                stopEnabled: true,
                markEnabled: false
            )

            var incomplete = GestureRecognitionStateMachine()
            incomplete.reset(at: 0, initialCooldown: 0)
            var incompleteTime: TimeInterval = 0
            let incompleteCommands = feed(
                machine: &incomplete,
                time: &incompleteTime,
                duration: 0.9,
                frameRate: frameRate,
                settings: stopOnly
            ) { timestamp in
                .openPalm(timestamp: timestamp, x: Self.waveX(at: timestamp), y: 0.5)
            }
            XCTAssertTrue(incompleteCommands.isEmpty, "Incomplete wave fired at \(frameRate) fps")

            var noisy = GestureRecognitionStateMachine()
            noisy.reset(at: 0, initialCooldown: 0)
            var noisyTime: TimeInterval = 0
            let noisyCommands = feed(
                machine: &noisy,
                time: &noisyTime,
                duration: 4.2,
                frameRate: frameRate,
                settings: stopOnly
            ) { timestamp in
                let x = 0.5 + sin(timestamp * 24) * 0.004
                return .openPalm(timestamp: timestamp, x: x, y: 0.5)
            }
            XCTAssertTrue(noisyCommands.isEmpty, "Wave noise fired at \(frameRate) fps")

            var wave = GestureRecognitionStateMachine()
            wave.reset(at: 0, initialCooldown: 0)
            var waveTime: TimeInterval = 0
            let waveCommands = feed(
                machine: &wave,
                time: &waveTime,
                duration: 4.2,
                frameRate: frameRate,
                settings: stopOnly
            ) { timestamp in
                .openPalm(timestamp: timestamp, x: Self.waveX(at: timestamp), y: 0.5)
            }
            XCTAssertEqual(waveCommands, [.stop], "Wave did not fire exactly once at \(frameRate) fps")
        }
    }

    func testPinchHoldMarksOnceAndRequiresFingerSeparation() {
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
            ) { timestamp in
                .pinch(timestamp: timestamp, distance: 0.03)
            }
            XCTAssertTrue(commands.isEmpty, "Short pinch fired at \(frameRate) fps")

            _ = feed(
                machine: &machine,
                time: &time,
                duration: 0.2,
                frameRate: frameRate,
                settings: markOnly
            ) { timestamp in
                .pinch(timestamp: timestamp, distance: 0.08)
            }

            commands += feed(
                machine: &machine,
                time: &time,
                duration: 2.2,
                frameRate: frameRate,
                settings: markOnly
            ) { timestamp in
                .pinch(timestamp: timestamp, distance: 0.03)
            }
            XCTAssertEqual(commands, [.markSegment], "Two-second pinch did not mark at \(frameRate) fps")

            commands += feed(
                machine: &machine,
                time: &time,
                duration: 3.0,
                frameRate: frameRate,
                settings: markOnly
            ) { timestamp in
                .pinch(timestamp: timestamp, distance: 0.03)
            }
            XCTAssertEqual(commands, [.markSegment], "Continued pinch duplicated mark at \(frameRate) fps")

            _ = feed(
                machine: &machine,
                time: &time,
                duration: 0.2,
                frameRate: frameRate,
                settings: markOnly
            ) { timestamp in
                .pinch(timestamp: timestamp, distance: 0.08)
            }

            commands += feed(
                machine: &machine,
                time: &time,
                duration: 2.2,
                frameRate: frameRate,
                settings: markOnly
            ) { timestamp in
                .pinch(timestamp: timestamp, distance: 0.03)
            }
            XCTAssertEqual(
                commands,
                [.markSegment, .markSegment],
                "Pinch did not rearm after separation at \(frameRate) fps"
            )
        }
    }

    func testDisabledGesturesDoNotAccumulateState() {
        for frameRate in frameRates {
            var machine = GestureRecognitionStateMachine()
            machine.reset(at: 0, initialCooldown: 0)
            var time: TimeInterval = 0
            let disabled = GestureRecognitionSettings(
                pauseEnabled: false,
                stopEnabled: false,
                markEnabled: false
            )

            var commands = feed(
                machine: &machine,
                time: &time,
                duration: 4.2,
                frameRate: frameRate,
                settings: disabled
            ) { timestamp in
                GestureRecognitionFrame(
                    timestamp: timestamp,
                    isOpenPalm: true,
                    wristX: Self.waveX(at: timestamp),
                    wristY: 0.5,
                    pinchDistance: 0.03
                )
            }
            XCTAssertTrue(commands.isEmpty, "Disabled gesture fired at \(frameRate) fps")

            let pauseOnly = GestureRecognitionSettings(
                pauseEnabled: true,
                stopEnabled: false,
                markEnabled: false
            )
            commands += feed(
                machine: &machine,
                time: &time,
                duration: 2.8,
                frameRate: frameRate,
                settings: pauseOnly
            ) { timestamp in
                .openPalm(timestamp: timestamp, x: 0.5, y: 0.5)
            }
            XCTAssertTrue(commands.isEmpty, "Disabled palm time carried over at \(frameRate) fps")

            commands += feed(
                machine: &machine,
                time: &time,
                duration: 0.4,
                frameRate: frameRate,
                settings: pauseOnly
            ) { timestamp in
                .openPalm(timestamp: timestamp, x: 0.5, y: 0.5)
            }
            XCTAssertEqual(commands, [.pause], "Fresh enabled hold failed at \(frameRate) fps")
        }
    }

    func testHandLossClearsPartialRecognition() {
        for frameRate in frameRates {
            var palm = GestureRecognitionStateMachine()
            palm.reset(at: 0, initialCooldown: 0)
            var palmTime: TimeInterval = 0
            let pauseOnly = GestureRecognitionSettings(
                pauseEnabled: true,
                stopEnabled: false,
                markEnabled: false
            )

            var palmCommands = feed(
                machine: &palm,
                time: &palmTime,
                duration: 2.4,
                frameRate: frameRate,
                settings: pauseOnly
            ) { timestamp in
                .openPalm(timestamp: timestamp, x: 0.5, y: 0.5)
            }
            _ = feed(
                machine: &palm,
                time: &palmTime,
                duration: 0.2,
                frameRate: frameRate,
                settings: pauseOnly
            ) { timestamp in
                .empty(timestamp: timestamp)
            }
            palmCommands += feed(
                machine: &palm,
                time: &palmTime,
                duration: 2.4,
                frameRate: frameRate,
                settings: pauseOnly
            ) { timestamp in
                .openPalm(timestamp: timestamp, x: 0.5, y: 0.5)
            }
            XCTAssertTrue(palmCommands.isEmpty, "Palm survived hand loss at \(frameRate) fps")

            palmCommands += feed(
                machine: &palm,
                time: &palmTime,
                duration: 0.8,
                frameRate: frameRate,
                settings: pauseOnly
            ) { timestamp in
                .openPalm(timestamp: timestamp, x: 0.5, y: 0.5)
            }
            XCTAssertEqual(palmCommands, [.pause], "Palm did not restart after hand loss at \(frameRate) fps")

            var pinch = GestureRecognitionStateMachine()
            pinch.reset(at: 0, initialCooldown: 0)
            var pinchTime: TimeInterval = 0
            let markOnly = GestureRecognitionSettings(
                pauseEnabled: false,
                stopEnabled: false,
                markEnabled: true
            )

            var pinchCommands = feed(
                machine: &pinch,
                time: &pinchTime,
                duration: 1.4,
                frameRate: frameRate,
                settings: markOnly
            ) { timestamp in
                .pinch(timestamp: timestamp, distance: 0.03)
            }
            _ = feed(
                machine: &pinch,
                time: &pinchTime,
                duration: 0.2,
                frameRate: frameRate,
                settings: markOnly
            ) { timestamp in
                .empty(timestamp: timestamp)
            }
            pinchCommands += feed(
                machine: &pinch,
                time: &pinchTime,
                duration: 1.4,
                frameRate: frameRate,
                settings: markOnly
            ) { timestamp in
                .pinch(timestamp: timestamp, distance: 0.03)
            }
            XCTAssertTrue(pinchCommands.isEmpty, "Pinch survived hand loss at \(frameRate) fps")
        }
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

    private static func waveX(at timestamp: TimeInterval) -> Double {
        let legDuration = 0.35
        let leg = Int(floor(timestamp / legDuration))
        let progress = (timestamp - Double(leg) * legDuration) / legDuration
        if leg.isMultiple(of: 2) {
            return 0.42 + 0.16 * progress
        }
        return 0.58 - 0.16 * progress
    }
}

private extension GestureRecognitionFrame {
    static func openPalm(timestamp: TimeInterval, x: Double, y: Double) -> Self {
        Self(
            timestamp: timestamp,
            isOpenPalm: true,
            wristX: x,
            wristY: y,
            pinchDistance: nil
        )
    }

    static func pinch(timestamp: TimeInterval, distance: Double) -> Self {
        Self(
            timestamp: timestamp,
            isOpenPalm: false,
            wristX: 0.5,
            wristY: 0.5,
            pinchDistance: distance
        )
    }

    static func empty(timestamp: TimeInterval) -> Self {
        Self(
            timestamp: timestamp,
            isOpenPalm: nil,
            wristX: nil,
            wristY: nil,
            pinchDistance: nil
        )
    }
}
