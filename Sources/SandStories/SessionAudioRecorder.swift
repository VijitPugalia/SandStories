import AVFoundation
import Foundation

/// Records microphone audio to a file for the active capture session.
@MainActor
final class SessionAudioRecorder: NSObject {
    private var recorder: AVAudioRecorder?
    private var recordingStartedUptime: TimeInterval?
    private var pauseStartedUptime: TimeInterval?
    private var accumulatedPauseDuration: TimeInterval = 0
    private(set) var permissionDenied: Bool = false

    func requestPermission() async -> Bool {
        let session = AVAudioSession.sharedInstance()
        switch session.recordPermission {
        case .granted:
            return true
        case .denied:
            permissionDenied = true
            return false
        case .undetermined:
            return await withCheckedContinuation { cont in
                session.requestRecordPermission { allowed in
                    cont.resume(returning: allowed)
                }
            }
        @unknown default:
            return false
        }
    }

    /// Returns (url, duration, sampleRate, channels) on success.
    func startRecording(to fileURL: URL) throws {
        permissionDenied = false
        let session = AVAudioSession.sharedInstance()
        try session.setCategory(.playAndRecord, mode: .default, options: [.defaultToSpeaker, .allowBluetooth])
        try session.setActive(true)

        let settings: [String: Any] = [
            AVFormatIDKey: Int(kAudioFormatMPEG4AAC),
            AVSampleRateKey: 44_100,
            AVNumberOfChannelsKey: 1,
            AVEncoderAudioQualityKey: AVAudioQuality.high.rawValue
        ]

        let recorder = try AVAudioRecorder(url: fileURL, settings: settings)
        recorder.prepareToRecord()
        guard recorder.record() else {
            throw NSError(domain: "SessionAudioRecorder", code: 1, userInfo: [NSLocalizedDescriptionKey: "record() failed"])
        }
        self.recorder = recorder
        recordingStartedUptime = ProcessInfo.processInfo.systemUptime
        pauseStartedUptime = nil
        accumulatedPauseDuration = 0
    }

    func pauseRecording() {
        guard let recorder, recorder.isRecording else { return }
        pauseStartedUptime = ProcessInfo.processInfo.systemUptime
        recorder.pause()
    }

    func resumeRecording() {
        guard let recorder, !recorder.isRecording else { return }
        if let pauseStartedUptime {
            accumulatedPauseDuration += max(
                0,
                ProcessInfo.processInfo.systemUptime - pauseStartedUptime
            )
        }
        self.pauseStartedUptime = nil
        recorder.record()
    }

    func stopRecording() -> (duration: TimeInterval, sampleRate: Double, channels: Int)? {
        guard let recorder else { return nil }
        let now = ProcessInfo.processInfo.systemUptime
        if let pauseStartedUptime {
            accumulatedPauseDuration += max(0, now - pauseStartedUptime)
        }
        let wallDuration = max(0, now - (recordingStartedUptime ?? now) - accumulatedPauseDuration)
        let duration = max(recorder.currentTime, wallDuration)
        let rate = recorder.settings[AVSampleRateKey] as? Double ?? 44_100
        let ch = recorder.settings[AVNumberOfChannelsKey] as? Int ?? 1
        recorder.stop()
        self.recorder = nil
        recordingStartedUptime = nil
        pauseStartedUptime = nil
        accumulatedPauseDuration = 0
        try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
        return (duration, rate, ch)
    }
}
