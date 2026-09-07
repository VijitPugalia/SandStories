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
    var isSaving: Bool = false
    let onChooseStorage: () -> Void
    let onExportLastSession: () -> Void

    private var storageKindText: String {
        destinationLabel.replacingOccurrences(of: "Saving to: ", with: "")
    }

    private var isExternalStorage: Bool {
        destinationLabel.contains("SSD") || destinationLabel.contains("External folder")
    }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    VStack(alignment: .leading, spacing: 8) {
                        Text("Captured stories")
                            .font(.title2.weight(.bold))
                        Text("Sessions are automatically saved immediately when recording stops. Review your saved captures or share a packaged ZIP.")
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
                Image(systemName: isExternalStorage ? "externaldrive.fill" : "internaldrive.fill")
                    .font(.title3)
                    .foregroundStyle(Color.accentColor)
                    .frame(width: 34, height: 34)
                VStack(alignment: .leading, spacing: 3) {
                    Text("Auto-save destination")
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(Color(uiColor: .secondaryLabel))
                    Text(storageKindText)
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
        .disabled(isRecording || isSaving)
        .opacity((isRecording || isSaving) ? 0.55 : 1)
        .accessibilityHint((isRecording || isSaving) ? "Wait until capture and saving are complete." : "Choose where new sessions are saved.")
    }

    private func latestSessionCard(_ folderURL: URL) -> some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack {
                Label("Latest session", systemImage: "checkmark.circle.fill")
                    .font(.headline)
                    .foregroundStyle(Color.accentColor)
                Spacer()
                Text("Saved")
                    .font(.caption2.weight(.bold))
                    .foregroundStyle(Color.accentColor)
                    .padding(.horizontal, 8)
                    .padding(.vertical, 3)
                    .background(Color.accentColor.opacity(0.12))
                    .clipShape(Capsule())
            }

            VStack(alignment: .leading, spacing: 4) {
                Text(folderURL.lastPathComponent)
                    .font(.body.monospaced().weight(.semibold))
                    .foregroundStyle(Color(uiColor: .label))
                    .lineLimit(2)

                Text(isExternalStorage ? "Saved directly on your external SSD" : "Saved on this iPhone (Files app > On My iPhone > SandStories > SandStoriesSessions)")
                    .font(.caption)
                    .foregroundStyle(Color(uiColor: .secondaryLabel))
            }

            Button(action: onExportLastSession) {
                Label("Share / AirDrop ZIP", systemImage: "square.and.arrow.up")
                    .font(.body.weight(.semibold))
                    .frame(maxWidth: .infinity)
                    .frame(height: 46)
            }
            .buttonStyle(.borderedProminent)
            .tint(Color(red: 0.94, green: 0.70, blue: 0.28))

            Text("This session is already stored automatically. Tap above only if you want to export an archive to AirDrop, Mail, or another app.")
                .font(.caption2)
                .foregroundStyle(Color(uiColor: .tertiaryLabel))
                .multilineTextAlignment(.center)
                .frame(maxWidth: .infinity)
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
            Text("Record a session in Capture and it will automatically save to your chosen storage.")
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
                }

                Section("Recording gestures") {
                    Toggle("Yo gesture pauses or resumes", isOn: $recordingCoordinator.isPauseGestureEnabled)
                    Toggle("Cover camera stops and saves", isOn: $recordingCoordinator.isStopGestureEnabled)
                    Toggle("Pinch and hold marks a segment", isOn: $recordingCoordinator.isMarkGestureEnabled)
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