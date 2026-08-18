import Foundation
import SwiftUI

enum SandStoriesTab: Hashable {
    case capture
    case sessions
    case settings
}

extension SandStoriesTab {
    var diagnosticsName: String {
        switch self {
        case .capture:
            return "Capture"
        case .sessions:
            return "Sessions"
        case .settings:
            return "Settings"
        }
    }
}

@MainActor
struct SessionsTabView: View {
    let destinationLabel: String
    let lastSessionFolderURL: URL?
    let isRecording: Bool
    let onChooseStorage: () -> Void
    let onExportLastSession: () -> Void

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    VStack(alignment: .leading, spacing: 8) {
                        Text("Captured stories")
                            .font(.title2.weight(.bold))
                        Text("Review where sessions are saved and export the latest complete capture.")
                            .font(.subheadline)
                            .foregroundStyle(Color(uiColor: .secondaryLabel))
                    }

                    storageCard

                    if let lastSessionFolderURL {
                        latestSessionCard(lastSessionFolderURL)
                    } else {
                        emptySessionsCard
                    }
                }
                .frame(maxWidth: 620, alignment: .leading)
                .padding(.horizontal, 20)
                .padding(.vertical, 18)
            }
            .background(Color(uiColor: .systemGroupedBackground).ignoresSafeArea())
            .navigationTitle("Sessions")
        }
    }

    private var storageCard: some View {
        Button(action: onChooseStorage) {
            HStack(spacing: 14) {
                Image(systemName: "internaldrive.fill")
                    .font(.title3)
                    .foregroundStyle(Color.accentColor)
                    .frame(width: 34, height: 34)
                VStack(alignment: .leading, spacing: 3) {
                    Text("Save location")
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(Color(uiColor: .secondaryLabel))
                    Text(destinationLabel.replacingOccurrences(of: "Saving to: ", with: ""))
                        .font(.body.weight(.semibold))
                        .foregroundStyle(Color(uiColor: .label))
                        .lineLimit(1)
                }
                Spacer()
                Image(systemName: "chevron.right")
                    .font(.caption.weight(.bold))
                    .foregroundStyle(Color(uiColor: .tertiaryLabel))
            }
            .padding(16)
            .glassPanel(cornerRadius: 20, blurStyle: .systemThinMaterial, shadowRadius: 8, shadowYOffset: 3)
        }
        .buttonStyle(.plain)
        .disabled(isRecording)
        .opacity(isRecording ? 0.55 : 1)
        .accessibilityHint(isRecording ? "Stop recording before changing storage." : "Choose where new sessions are saved.")
    }

    private func latestSessionCard(_ folderURL: URL) -> some View {
        VStack(alignment: .leading, spacing: 14) {
            Label("Latest session", systemImage: "checkmark.circle.fill")
                .font(.headline)
                .foregroundStyle(Color.accentColor)

            Text(folderURL.lastPathComponent)
                .font(.body.monospaced().weight(.semibold))
                .foregroundStyle(Color(uiColor: .label))
                .lineLimit(2)

            Button(action: onExportLastSession) {
                Label("Export last session", systemImage: "square.and.arrow.up")
                    .font(.body.weight(.semibold))
                    .frame(maxWidth: .infinity)
                    .frame(height: 46)
            }
            .buttonStyle(.borderedProminent)
            .tint(Color(red: 0.94, green: 0.70, blue: 0.28))
        }
        .padding(18)
        .glassPanel(cornerRadius: 22, blurStyle: .systemThinMaterial, shadowRadius: 10, shadowYOffset: 4)
    }

    private var emptySessionsCard: some View {
        VStack(spacing: 12) {
            Image(systemName: "rectangle.stack")
                .font(.system(size: 34, weight: .medium))
                .foregroundStyle(Color(uiColor: .secondaryLabel))
            Text("No completed session yet")
                .font(.headline)
            Text("Record a session in Capture and it will appear here for export.")
                .font(.subheadline)
                .foregroundStyle(Color(uiColor: .secondaryLabel))
                .multilineTextAlignment(.center)
        }
        .frame(maxWidth: .infinity)
        .padding(.horizontal, 22)
        .padding(.vertical, 34)
        .glassPanel(cornerRadius: 22, blurStyle: .systemThinMaterial, shadowRadius: 8, shadowYOffset: 3)
    }
}

@MainActor
struct SettingsTabView: View {
    @ObservedObject var recordingCoordinator: RecordingCoordinator
    @ObservedObject var diagnostics: AppDiagnostics
    let onChooseStorage: () -> Void
    let onShowUploadSettings: () -> Void

    private var toolsAreBusy: Bool {
        recordingCoordinator.isCaptureRecording ||
            recordingCoordinator.isBenchmarkRunning ||
            recordingCoordinator.isDepthDiagnosticRunning
    }

    var body: some View {
        NavigationStack {
            Form {
                Section("Capture") {
                    Button(action: onChooseStorage) {
                        Label(recordingCoordinator.destinationLabel, systemImage: "internaldrive")
                    }
                    .disabled(recordingCoordinator.isCaptureRecording)

                    Toggle("Show LiDAR mesh", isOn: $recordingCoordinator.isMeshVisualizationEnabled)
                        .disabled(recordingCoordinator.isCaptureRecording)

                    Toggle("Raw depth diagnostic only", isOn: $recordingCoordinator.isDepthDiagnosticRawOnly)
                        .disabled(toolsAreBusy)

                    Toggle("Auto-calibrate motion gate from baseline", isOn: $recordingCoordinator.isMotionGateCalibrationEnabled)
                        .disabled(recordingCoordinator.isCaptureRecording)
                }

                Section("Recording gestures") {
                    Toggle("Open palm pauses or resumes", isOn: $recordingCoordinator.isPauseGestureEnabled)
                    Toggle("Wave stops recording", isOn: $recordingCoordinator.isStopGestureEnabled)
                    Toggle("One-finger triple tap marks a segment", isOn: $recordingCoordinator.isMarkGestureEnabled)
                }

                Section("Capture tools") {
                    Button {
                        Task {
                            await recordingCoordinator.handPoseManager.clearStrokes()
                        }
                    } label: {
                        Label("Clear visible strokes", systemImage: "paintbrush.pointed")
                    }

                    Button {
                        Task {
                            await recordingCoordinator.runDepthBenchmark()
                        }
                    } label: {
                        Label(
                            recordingCoordinator.isBenchmarkRunning ? "Benchmark running…" : "Run depth benchmark",
                            systemImage: "speedometer"
                        )
                    }
                    .disabled(toolsAreBusy)

                    Button {
                        Task {
                            await recordingCoordinator.runDepthDiagnostic()
                        }
                    } label: {
                        Label(
                            recordingCoordinator.isDepthDiagnosticRunning ? "Diagnostic running…" : "Run depth diagnostic",
                            systemImage: "waveform.path.ecg"
                        )
                    }
                    .disabled(toolsAreBusy)
                }

                Section("Upload") {
                    Button(action: onShowUploadSettings) {
                        Label(
                            recordingCoordinator.uploadSettings.enabled ? "Upload enabled" : "Upload settings",
                            systemImage: recordingCoordinator.uploadSettings.enabled ? "icloud.and.arrow.up.fill" : "icloud.and.arrow.up"
                        )
                    }
                    .disabled(recordingCoordinator.isCaptureRecording)
                }

                Section("Support") {
                    NavigationLink {
                        DiagnosticsView(diagnostics: diagnostics)
                    } label: {
                        Label("App diagnostics", systemImage: "waveform.path.ecg.rectangle")
                    }
                }
            }
            .navigationTitle("Settings")
        }
    }
}