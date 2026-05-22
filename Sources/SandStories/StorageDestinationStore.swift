import Foundation

enum CaptureStorageKind: String, Codable {
    case internalDocuments
    case externalBookmark
}

/// Persists last-used capture destination (internal vs security-scoped external folder).
final class StorageDestinationStore {
    private let defaults = UserDefaults.standard
    private let kindKey = "sandstories.capture.storageKind"
    private let bookmarkKey = "sandstories.capture.externalBookmark"
    private let displayNameKey = "sandstories.capture.externalDisplayName"

    func currentKind() -> CaptureStorageKind {
        guard let raw = defaults.string(forKey: kindKey),
              let k = CaptureStorageKind(rawValue: raw) else {
            return .internalDocuments
        }
        return k
    }

    func setInternal() {
        defaults.set(CaptureStorageKind.internalDocuments.rawValue, forKey: kindKey)
        defaults.removeObject(forKey: bookmarkKey)
        defaults.removeObject(forKey: displayNameKey)
    }

    func setExternalBookmark(data: Data, displayName: String) {
        defaults.set(CaptureStorageKind.externalBookmark.rawValue, forKey: kindKey)
        defaults.set(data, forKey: bookmarkKey)
        defaults.set(displayName, forKey: displayNameKey)
    }

    func externalDisplayName() -> String? {
        defaults.string(forKey: displayNameKey)
    }

    /// Resolves bookmark and starts security-scoped access (caller must stop when done, or keep for session).
    func resolveExternalFolderURL() throws -> URL? {
        guard let data = defaults.data(forKey: bookmarkKey) else { return nil }
        var stale = false
        // iOS: `.withSecurityScope` is unavailable; use `startAccessingSecurityScopedResource()` on the resolved URL.
        let url = try URL(
            resolvingBookmarkData: data,
            options: [],
            relativeTo: nil,
            bookmarkDataIsStale: &stale
        )
        if stale {
            // Bookmark stale — caller should re-pick.
            return nil
        }
        return url
    }
}
