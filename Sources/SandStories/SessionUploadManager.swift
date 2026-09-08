import Combine
import CryptoKit
import Foundation

struct SessionPackageManifest: Codable, Sendable {
    var schemaVersion: Int
    var sessionId: String
    var sessionFolderName: String
    var createdAtUnix: TimeInterval
    var files: [FileEntry]

    struct FileEntry: Codable, Sendable {
        var relativePath: String
        var size: Int64
        var sha256: String
    }
}

@MainActor
final class UploadSettingsStore: ObservableObject {
    private let defaults = UserDefaults.standard
    private let enabledKey = "upload.enabled"
    private let endpointKey = "upload.endpoint"

    @Published var enabled: Bool {
        didSet { defaults.set(enabled, forKey: enabledKey) }
    }

    @Published var endpoint: String {
        didSet { defaults.set(endpoint, forKey: endpointKey) }
    }

    init() {
        enabled = defaults.bool(forKey: enabledKey)
        endpoint = defaults.string(forKey: endpointKey) ?? ""
    }

    func isEnabled() -> Bool {
        enabled
    }

    func endpointURL() -> URL? {
        guard let url = URL(string: endpoint.trimmingCharacters(in: .whitespacesAndNewlines)),
              ["http", "https"].contains(url.scheme?.lowercased() ?? ""),
              let host = url.host, !host.isEmpty,
              !["localhost", "127.0.0.1", "::1", "[::1]", "0.0.0.0"].contains(host.lowercased()) else { return nil }
        return url
    }
}

actor SessionUploadManager {
    func uploadSessionFolder(_ sessionFolder: URL, to endpoint: URL) async throws {
        let packageManifest = try writePackageManifest(for: sessionFolder)
        let zipURL = try temporaryZipURL(for: sessionFolder)
        if FileManager.default.fileExists(atPath: zipURL.path) {
            try? FileManager.default.removeItem(at: zipURL)
        }

        try SimpleZipWriter().writeZip(storingDirectoryTree: sessionFolder, to: zipURL)
        let zipSHA256 = try sha256Hex(for: zipURL)
        defer { try? FileManager.default.removeItem(at: zipURL) }

        var request = URLRequest(url: endpoint)
        request.httpMethod = "POST"
        request.setValue("application/zip", forHTTPHeaderField: "Content-Type")
        request.setValue(sessionFolder.lastPathComponent + ".zip", forHTTPHeaderField: "X-SandStories-Filename")
        request.setValue(packageManifest.sessionId, forHTTPHeaderField: "X-SandStories-Session-Id")
        request.setValue(zipSHA256, forHTTPHeaderField: "X-SandStories-SHA256")

        let (_, response) = try await URLSession.shared.upload(for: request, fromFile: zipURL)
        guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
            let code = (response as? HTTPURLResponse)?.statusCode ?? -1
            throw NSError(domain: "SessionUploadManager", code: code, userInfo: [NSLocalizedDescriptionKey: "Server returned HTTP \(code)"])
        }
    }

    private func temporaryZipURL(for sessionFolder: URL) throws -> URL {
        let temp = FileManager.default.temporaryDirectory.appendingPathComponent("SandStoriesUploads", isDirectory: true)
        try FileManager.default.createDirectory(at: temp, withIntermediateDirectories: true)
        return temp.appendingPathComponent(sessionFolder.lastPathComponent + ".zip")
    }

    @discardableResult
    private func writePackageManifest(for sessionFolder: URL) throws -> SessionPackageManifest {
        let fm = FileManager.default
        let sessionId = try readSessionId(from: sessionFolder) ?? sessionFolder.lastPathComponent.replacingOccurrences(of: "session_", with: "")
        let entries = try packageFileEntries(for: sessionFolder)
        let manifest = SessionPackageManifest(
            schemaVersion: 1,
            sessionId: sessionId,
            sessionFolderName: sessionFolder.lastPathComponent,
            createdAtUnix: Date().timeIntervalSince1970,
            files: entries
        )

        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes]
        let data = try encoder.encode(manifest)
        let url = sessionFolder.appendingPathComponent("package_manifest.json")
        if fm.fileExists(atPath: url.path) {
            try? fm.removeItem(at: url)
        }
        try data.write(to: url, options: [.atomic])
        return manifest
    }

    private func packageFileEntries(for sessionFolder: URL) throws -> [SessionPackageManifest.FileEntry] {
        let fm = FileManager.default
        let rootPath = sessionFolder.path
        guard let enumerator = fm.enumerator(
            at: sessionFolder,
            includingPropertiesForKeys: [.isRegularFileKey, .fileSizeKey],
            options: [.skipsHiddenFiles]
        ) else {
            throw NSError(domain: "SessionUploadManager", code: 10, userInfo: [NSLocalizedDescriptionKey: "Could not enumerate session folder"])
        }

        var entries: [SessionPackageManifest.FileEntry] = []
        while let item = enumerator.nextObject() as? URL {
            let values = try item.resourceValues(forKeys: [.isRegularFileKey, .fileSizeKey])
            guard values.isRegularFile == true else { continue }
            var rel = String(item.path.dropFirst(rootPath.count))
            if rel.hasPrefix("/") { rel.removeFirst() }
            rel = rel.replacingOccurrences(of: "\\", with: "/")
            guard !rel.isEmpty, rel != "package_manifest.json" else { continue }
            entries.append(
                .init(
                    relativePath: rel,
                    size: Int64(values.fileSize ?? 0),
                    sha256: try sha256Hex(for: item)
                )
            )
        }
        entries.sort { $0.relativePath < $1.relativePath }
        return entries
    }

    private func readSessionId(from sessionFolder: URL) throws -> String? {
        let manifestURL = sessionFolder.appendingPathComponent("manifest.json")
        guard FileManager.default.fileExists(atPath: manifestURL.path) else { return nil }
        let data = try Data(contentsOf: manifestURL)
        guard let json = try JSONSerialization.jsonObject(with: data) as? [String: Any] else { return nil }
        return json["sessionId"] as? String
    }

    private func sha256Hex(for url: URL) throws -> String {
        let handle = try FileHandle(forReadingFrom: url)
        defer { try? handle.close() }
        var hasher = SHA256()
        while let chunk = try handle.read(upToCount: 1024 * 1024), !chunk.isEmpty {
            hasher.update(data: chunk)
        }
        return hasher.finalize().map { String(format: "%02hhx", $0) }.joined()
    }
}
