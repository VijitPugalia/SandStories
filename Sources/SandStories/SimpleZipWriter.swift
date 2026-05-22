import Foundation

/// Minimal ZIP writer that uses "store" (no compression) method.
/// Good enough for bundling PNG files without external zlib dependencies.
final class SimpleZipWriter {
    enum ZipError: Error {
        case fileReadFailed(URL)
        case invalidFilename(String)
    }

    /// Zips all regular files under `root`, preserving relative paths (sorted for deterministic output).
    func writeZip(storingDirectoryTree root: URL, to zipURL: URL) throws {
        let fm = FileManager.default
        var entries: [(url: URL, nameInZip: String)] = []
        let rootPath = root.path
        guard let enumerator = fm.enumerator(
            at: root,
            includingPropertiesForKeys: [.isRegularFileKey],
            options: [.skipsHiddenFiles]
        ) else {
            throw ZipError.fileReadFailed(root)
        }
        while let item = enumerator.nextObject() as? URL {
            let rv = try item.resourceValues(forKeys: [.isRegularFileKey])
            guard rv.isRegularFile == true else { continue }
            var rel = String(item.path.dropFirst(rootPath.count))
            if rel.hasPrefix("/") {
                rel.removeFirst()
            }
            let zipName = rel.replacingOccurrences(of: "\\", with: "/")
            guard !zipName.isEmpty else { continue }
            entries.append((item, zipName))
        }
        entries.sort { $0.nameInZip < $1.nameInZip }
        try writeZip(storingEntries: entries.map { ($0.url, $0.nameInZip) }, to: zipURL)
    }

    func writeZip(storingFiles fileURLs: [URL], to zipURL: URL) throws {
        let entries = fileURLs.map { ($0, $0.lastPathComponent) }
        try writeZip(storingEntries: entries, to: zipURL)
    }

    func writeZip(storingEntries entries: [(URL, String)], to zipURL: URL) throws {
        var out = Data()

        struct CentralDirectoryEntry {
            let name: String
            let crc32: UInt32
            let compressedSize: UInt32
            let uncompressedSize: UInt32
            let localHeaderOffset: UInt32
        }

        var central: [CentralDirectoryEntry] = []

        for (fileURL, name) in entries {
            guard name.utf8.count <= UInt16.max else { throw ZipError.invalidFilename(name) }

            guard let fileData = try? Data(contentsOf: fileURL) else {
                throw ZipError.fileReadFailed(fileURL)
            }

            let crc = CRC32.checksum(fileData)
            let size = UInt32(fileData.count)
            let localOffset = UInt32(out.count)

            // Local file header
            // signature(4) + ver(2) + flags(2) + method(2) + time(2) + date(2) + crc(4) + csize(4) + usize(4)
            // + nameLen(2) + extraLen(2) + name + extra + filedata
            out.appendLE(UInt32(0x04034b50))
            out.appendLE(UInt16(20)) // version needed to extract
            out.appendLE(UInt16(0))  // flags
            out.appendLE(UInt16(0))  // compression = store
            out.appendLE(UInt16(0))  // mod time
            out.appendLE(UInt16(0))  // mod date
            out.appendLE(crc)
            out.appendLE(size) // compressed size
            out.appendLE(size) // uncompressed size
            out.appendLE(UInt16(name.utf8.count))
            out.appendLE(UInt16(0)) // extra len
            out.append(name.data(using: .utf8)!)
            out.append(fileData)

            central.append(
                CentralDirectoryEntry(
                    name: name,
                    crc32: crc,
                    compressedSize: size,
                    uncompressedSize: size,
                    localHeaderOffset: localOffset
                )
            )
        }

        let centralDirectoryOffset = UInt32(out.count)

        // Central directory records
        for entry in central {
            let nameData = entry.name.data(using: .utf8)!

            out.appendLE(UInt32(0x02014b50)) // central file header signature
            out.appendLE(UInt16(20)) // version made by
            out.appendLE(UInt16(20)) // version needed to extract
            out.appendLE(UInt16(0))  // flags
            out.appendLE(UInt16(0))  // method store
            out.appendLE(UInt16(0))  // mod time
            out.appendLE(UInt16(0))  // mod date
            out.appendLE(entry.crc32)
            out.appendLE(entry.compressedSize)
            out.appendLE(entry.uncompressedSize)
            out.appendLE(UInt16(nameData.count))
            out.appendLE(UInt16(0)) // extra len
            out.appendLE(UInt16(0)) // comment len
            out.appendLE(UInt16(0)) // disk number
            out.appendLE(UInt16(0)) // internal attrs
            out.appendLE(UInt32(0)) // external attrs
            out.appendLE(entry.localHeaderOffset)
            out.append(nameData)
        }

        let centralDirectorySize = UInt32(out.count) - centralDirectoryOffset

        // End of central directory record
        out.appendLE(UInt32(0x06054b50))
        out.appendLE(UInt16(0)) // disk number
        out.appendLE(UInt16(0)) // start disk
        out.appendLE(UInt16(central.count))
        out.appendLE(UInt16(central.count))
        out.appendLE(centralDirectorySize)
        out.appendLE(centralDirectoryOffset)
        out.appendLE(UInt16(0)) // comment len

        try out.write(to: zipURL, options: [.atomic])
    }
}

private enum CRC32 {
    private static let table: [UInt32] = {
        (0..<256).map { i -> UInt32 in
            var c = UInt32(i)
            for _ in 0..<8 {
                c = (c & 1) != 0 ? (0xEDB88320 ^ (c >> 1)) : (c >> 1)
            }
            return c
        }
    }()

    static func checksum(_ data: Data) -> UInt32 {
        var crc: UInt32 = 0xFFFFFFFF
        for b in data {
            let idx = Int((crc ^ UInt32(b)) & 0xFF)
            crc = table[idx] ^ (crc >> 8)
        }
        return crc ^ 0xFFFFFFFF
    }
}

private extension Data {
    mutating func appendLE(_ v: UInt16) {
        var x = v.littleEndian
        Swift.withUnsafeBytes(of: &x) { append(contentsOf: $0) }
    }

    mutating func appendLE(_ v: UInt32) {
        var x = v.littleEndian
        Swift.withUnsafeBytes(of: &x) { append(contentsOf: $0) }
    }
}

