import SwiftUI

// MARK: - Storage destination (bottom sheet)

struct StorageDestinationSheet: View {
    @Environment(\.dismiss) private var dismiss

    let destinationLabel: String
    let onSelectInternal: () -> Void
    let onSelectExternalSSD: () -> Void

    private var isInternalSelected: Bool {
        destinationLabel.contains("Internal") && !destinationLabel.contains("SSD")
    }

    private var isExternalSelected: Bool {
        destinationLabel.contains("SSD") || destinationLabel.contains("External folder")
    }

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                Text("Choose where new sessions are saved.")
                    .font(.subheadline)
                    .foregroundStyle(Color(uiColor: .secondaryLabel))
                    .multilineTextAlignment(.center)
                    .padding(.horizontal, 24)
                    .padding(.top, 8)
                    .padding(.bottom, 20)

                VStack(spacing: 12) {
                    destinationOptionRow(
                        title: "Internal Storage",
                        subtitle: "App Documents on this iPhone",
                        systemImage: "internaldrive",
                        isSelected: isInternalSelected
                    ) {
                        onSelectInternal()
                        dismiss()
                    }

                    destinationOptionRow(
                        title: "External SSD",
                        subtitle: "USB-C drive or Files folder",
                        systemImage: "externaldrive.connected.to.line.below",
                        isSelected: isExternalSelected
                    ) {
                        dismiss()
                        DispatchQueue.main.asyncAfter(deadline: .now() + 0.35) {
                            onSelectExternalSSD()
                        }
                    }
                }
                .padding(.horizontal, 20)

                Spacer(minLength: 12)

                Button("Done") {
                    dismiss()
                }
                .font(.body.weight(.semibold))
                .foregroundStyle(Color.accentColor)
                .frame(maxWidth: .infinity)
                .frame(minHeight: 44)
                .padding(.vertical, 8)
                .padding(.horizontal, 20)
                .padding(.bottom, 8)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .background(Color(uiColor: .systemGroupedBackground))
            .navigationTitle("Save location")
            .navigationBarTitleDisplayMode(.inline)
        }
    }

    private func destinationOptionRow(
        title: String,
        subtitle: String,
        systemImage: String,
        isSelected: Bool,
        action: @escaping () -> Void
    ) -> some View {
        Button(action: action) {
            HStack(alignment: .center, spacing: 16) {
                Image(systemName: systemImage)
                    .font(.title2)
                    .foregroundStyle(Color.accentColor)
                    .frame(width: 44, height: 44)

                VStack(alignment: .leading, spacing: 4) {
                    Text(title)
                        .font(.headline)
                        .foregroundStyle(Color(uiColor: .label))
                    Text(subtitle)
                        .font(.caption)
                        .foregroundStyle(Color(uiColor: .secondaryLabel))
                }

                Spacer(minLength: 8)

                if isSelected {
                    Image(systemName: "checkmark.circle.fill")
                        .font(.title3)
                        .symbolRenderingMode(.hierarchical)
                        .foregroundStyle(Color.accentColor)
                }
            }
            .padding(.vertical, 14)
            .padding(.horizontal, 16)
            .frame(minHeight: 44)
            .background {
                RoundedRectangle(cornerRadius: 16, style: .continuous)
                    .fill(Color(uiColor: .secondarySystemGroupedBackground))
            }
            .overlay {
                RoundedRectangle(cornerRadius: 16, style: .continuous)
                    .stroke(
                        isSelected ? Color.accentColor.opacity(0.45) : Color(uiColor: .separator).opacity(0.35),
                        lineWidth: isSelected ? 2 : 1
                    )
            }
        }
        .buttonStyle(.plain)
    }
}

// MARK: - Export / share preview (glass modal)

struct ExportSessionPreviewSheet: View {
    @Environment(\.dismiss) private var dismiss

    let sessionFolderName: String
    let onShare: () -> Void

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                Text(sessionFolderName)
                    .font(.caption)
                    .foregroundStyle(Color(uiColor: .tertiaryLabel))
                    .padding(.top, 4)

                List {
                    Section {
                        sessionContentRow("Manifest", "manifest.json", "doc.text")
                        sessionContentRow("Audio", "audio.m4a", "waveform")
                        sessionContentRow("Depth frames", "depth/", "square.stack.3d.down.right")
                        sessionContentRow("RGB frames", "rgb/", "photo.on.rectangle.angled")
                        sessionContentRow("Strokes", "strokes.json", "hand.draw")
                        sessionContentRow("Object detections", "objects.jsonl", "viewfinder")
                    } header: {
                        Text("Session package")
                            .font(.subheadline)
                            .foregroundStyle(Color(uiColor: .secondaryLabel))
                    }
                }
                .listStyle(.insetGrouped)
                .scrollContentBackground(.hidden)

                Button(action: onShare) {
                    Label("Share Session ZIP", systemImage: "square.and.arrow.up")
                        .font(.headline)
                        .frame(maxWidth: .infinity)
                        .frame(minHeight: 44)
                }
                .buttonStyle(.borderedProminent)
                .tint(Color.accentColor)
                .padding(.horizontal, 20)
                .padding(.vertical, 16)
                .background {
                    VisualEffectBlur(style: .systemThinMaterial)
                        .ignoresSafeArea(edges: .bottom)
                }
            }
            .background(Color(uiColor: .systemGroupedBackground))
            .navigationTitle("Export session")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Close") {
                        dismiss()
                    }
                    .foregroundStyle(Color(uiColor: .secondaryLabel))
                }
            }
        }
    }

    private func sessionContentRow(_ title: String, _ detail: String, _ symbol: String) -> some View {
        HStack(spacing: 14) {
            Image(systemName: symbol)
                .font(.body)
                .foregroundStyle(Color.accentColor)
                .frame(width: 28, alignment: .center)
            VStack(alignment: .leading, spacing: 2) {
                Text(title)
                    .font(.body)
                    .foregroundStyle(Color(uiColor: .label))
                Text(detail)
                    .font(.caption)
                    .foregroundStyle(Color(uiColor: .secondaryLabel))
            }
        }
        .padding(.vertical, 4)
    }
}

// MARK: - Upload settings

struct UploadSettingsSheet: View {
    @Environment(\.dismiss) private var dismiss
    @ObservedObject var settings: UploadSettingsStore
    @ObservedObject var experimentSettings: ExperimentServerSettings

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    Toggle("Auto-upload after recording", isOn: $settings.enabled)
                    TextField("Server upload URL", text: $settings.endpoint)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .keyboardType(.URL)
                } header: {
                    Text("Session upload")
                } footer: {
                    Text("Run the receiver on your computer and use a URL like http://192.168.1.20:8080/upload. Upload sends the completed session as a ZIP.")
                }

                Section {
                    Toggle("Enable remote console", isOn: $experimentSettings.enabled)
                    Toggle("Enable remote preview", isOn: $experimentSettings.previewEnabled)
                    if experimentSettings.previewEnabled {
                        Picker("Preview transport", selection: $experimentSettings.previewTransport) {
                            ForEach(PreviewTransport.allCases) { transport in
                                Text(transport.label).tag(transport)
                            }
                        }
                        Text("Refresh rate: \(Int(experimentSettings.previewFPS)) fps")
                        Slider(value: $experimentSettings.previewFPS, in: 1...15, step: 1)
                            .accessibilityLabel("Preview refresh rate")
                            .accessibilityValue("\(Int(experimentSettings.previewFPS)) frames per second")
                        Text(experimentSettings.previewTransport == .tunnel
                             ? "Uses this console connection. Works through the 8080 Tunnel; LiveKit is off."
                             : "Uses the server's LiveKit service, which needs a reachable media connection.")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    TextField("Console server URL", text: $experimentSettings.serverURL)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .keyboardType(.URL)
                    TextField("Device token", text: $experimentSettings.deviceToken)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                    TextField("Device name", text: $experimentSettings.deviceName)
                } header: {
                    Text("Field console")
                } footer: {
                    Text("Use your HTTPS field console URL, or http://YOUR-LAN-IP:8080 on a local network. Localhost points to this iPhone. Changes reconnect automatically.")
                }
            }
            .navigationTitle("Upload Settings")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Done") { dismiss() }
                }
            }
        }
    }
}
