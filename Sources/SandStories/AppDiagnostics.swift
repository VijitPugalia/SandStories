import Foundation
import OSLog
import SwiftUI
import UIKit

@MainActor
final class AppDiagnostics: ObservableObject {
    struct Entry: Codable, Identifiable {
        let id: UUID
        let timestamp: Date
        let category: String
        let message: String
    }

    static let shared = AppDiagnostics()

    @Published private(set) var entries: [Entry] = []

    private let logger = Logger(
        subsystem: Bundle.main.bundleIdentifier ?? "com.vijitpugalia.sandstories",
        category: "Diagnostics"
    )
    private let maximumEntryCount = 250
    private var recordedKeys: Set<String> = []

    private init() {
        loadPersistedEntries()
    }

    var appVersion: String {
        Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "unknown"
    }

    var buildNumber: String {
        Bundle.main.object(forInfoDictionaryKey: "CFBundleVersion") as? String ?? "unknown"
    }

    var buildCommit: String {
        let value = Bundle.main.object(forInfoDictionaryKey: "SandStoriesBuildCommit") as? String ?? "local"
        return value.count > 12 ? String(value.prefix(12)) : value
    }

    var buildRun: String {
        Bundle.main.object(forInfoDictionaryKey: "SandStoriesBuildRun") as? String ?? "local"
    }

    var navigationMode: String {
        if #available(iOS 26.0, *) {
            return "iOS 26 Liquid Glass"
        }
        return "Legacy tab bar"
    }

    var reportText: String {
        let header = [
            "SandStories diagnostics",
            "Generated: \(Date().ISO8601Format())",
            "App: \(appVersion) (\(buildNumber))",
            "Build run: \(buildRun)",
            "Commit: \(buildCommit)",
            "Bundle: \(Bundle.main.bundleIdentifier ?? "unknown")",
            "Device: \(UIDevice.current.model)",
            "iOS: \(UIDevice.current.systemVersion)",
            "Navigation path: \(navigationMode)",
            "Entries: \(entries.count)",
            ""
        ]

        let eventLines = entries.map { entry in
            "\(entry.timestamp.ISO8601Format()) [\(entry.category)] \(entry.message)"
        }
        return (header + eventLines).joined(separator: "\n")
    }

    func recordLaunchContext() {
        recordOnce(
            key: "launch-context",
            category: "App",
            message: "Launched \(appVersion) (\(buildNumber)), run \(buildRun), commit \(buildCommit), iOS \(UIDevice.current.systemVersion)"
        )
        recordOnce(
            key: "navigation-mode",
            category: "Navigation",
            message: "Selected runtime path: \(navigationMode)"
        )
    }

    func record(_ message: String, category: String) {
        let entry = Entry(id: UUID(), timestamp: Date(), category: category, message: message)
        entries.append(entry)
        if entries.count > maximumEntryCount {
            entries.removeFirst(entries.count - maximumEntryCount)
        }
        logger.notice("[\(category, privacy: .public)] \(message, privacy: .public)")
        persistEntries()
    }

    func recordOnce(key: String, category: String, message: String) {
        guard recordedKeys.insert(key).inserted else { return }
        record(message, category: category)
    }

    func clear() {
        entries.removeAll()
        persistEntries()
        logger.notice("Diagnostics history cleared")
    }

    private var persistedEntriesURL: URL? {
        FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask).first?
            .appendingPathComponent("sandstories-diagnostics.json")
    }

    private func loadPersistedEntries() {
        guard
            let url = persistedEntriesURL,
            let data = try? Data(contentsOf: url),
            let decoded = try? JSONDecoder().decode([Entry].self, from: data)
        else { return }
        entries = Array(decoded.suffix(maximumEntryCount))
    }

    private func persistEntries() {
        guard let url = persistedEntriesURL else { return }
        do {
            let data = try JSONEncoder().encode(entries)
            try data.write(to: url, options: .atomic)
        } catch {
            logger.error("Unable to persist diagnostics: \(error.localizedDescription, privacy: .public)")
        }
    }
}

@MainActor
struct DiagnosticsView: View {
    @ObservedObject var diagnostics: AppDiagnostics
    @State private var copied = false

    var body: some View {
        List {
            Section {
                diagnosticRow("App", value: "\(diagnostics.appVersion) (\(diagnostics.buildNumber))")
                diagnosticRow("Actions run", value: diagnostics.buildRun)
                diagnosticRow("Commit", value: diagnostics.buildCommit)
                diagnosticRow("iOS", value: UIDevice.current.systemVersion)
                diagnosticRow("Navigation", value: diagnostics.navigationMode)
            } header: {
                Label("Runtime fingerprint", systemImage: "fingerprint")
            } footer: {
                Text("Use these values to confirm which IPA and navigation path are actually running on the phone.")
            }

            Section("Actions") {
                Button {
                    UIPasteboard.general.string = diagnostics.reportText
                    copied = true
                    diagnostics.record("Diagnostics copied to clipboard", category: "Diagnostics")
                } label: {
                    Label(copied ? "Copied" : "Copy diagnostics", systemImage: copied ? "checkmark" : "doc.on.doc")
                }

                ShareLink(item: diagnostics.reportText) {
                    Label("Share diagnostics", systemImage: "square.and.arrow.up")
                }

                Button("Clear event history", role: .destructive) {
                    diagnostics.clear()
                }
            }

            Section("Recent events") {
                if diagnostics.entries.isEmpty {
                    Text("No events recorded yet. Switch tabs and return here to capture navigation activity.")
                        .foregroundStyle(.secondary)
                } else {
                    ForEach(diagnostics.entries.reversed()) { entry in
                        VStack(alignment: .leading, spacing: 4) {
                            HStack {
                                Text(entry.category.uppercased())
                                    .font(.caption2.weight(.bold))
                                    .foregroundStyle(Color.accentColor)
                                Spacer()
                                Text(entry.timestamp.formatted(date: .omitted, time: .standard))
                                    .font(.caption2.monospacedDigit())
                                    .foregroundStyle(.secondary)
                            }
                            Text(entry.message)
                                .font(.caption.monospaced())
                                .textSelection(.enabled)
                        }
                        .padding(.vertical, 3)
                    }
                }
            }
        }
        .navigationTitle("Diagnostics")
        .navigationBarTitleDisplayMode(.inline)
        .onAppear {
            diagnostics.record("Diagnostics screen opened", category: "Diagnostics")
        }
    }

    private func diagnosticRow(_ label: String, value: String) -> some View {
        LabeledContent(label) {
            Text(value)
                .font(.callout.monospaced())
                .foregroundStyle(.secondary)
                .textSelection(.enabled)
        }
    }
}
