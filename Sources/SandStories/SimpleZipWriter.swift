import Foundation

/// Minimal ZIP writer that uses "store" (no compression) method.
/// Good enough for bundling PNG files without external zlib dependencies.
final class SimpleZipWriter {
    enum ZipError: Error {
        case fileReadFailed(URL)
        case invalidFilename(String)
        case fileTooLarge(URL)
        case archiveTooLarge(URL)
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
        struct CentralDirectoryEntry {
            let name: String
            let crc32: UInt32
            let compressedSize: UInt32
            let uncompressedSize: UInt32
            let localHeaderOffset: UInt32
        }

        var central: [CentralDirectoryEntry] = []

        FileManager.default.createFile(atPath: zipURL.path, contents: nil)
        let out = try FileHandle(forWritingTo: zipURL)
        defer { try? out.close() }

        for (fileURL, name) in entries {
            guard name.utf8.count <= UInt16.max else { throw ZipError.invalidFilename(name) }

            let info = try CRC32.checksumAndSize(fileURL)
            guard info.size <= UInt64(UInt32.max) else { throw ZipError.fileTooLarge(fileURL) }
            let size = UInt32(info.size)
            let currentOffset = try out.offset()
            guard currentOffset <= UInt64(UInt32.max) else { throw ZipError.archiveTooLarge(zipURL) }
            let localOffset = UInt32(currentOffset)

            // Local file header
            // signature(4) + ver(2) + flags(2) + method(2) + time(2) + date(2) + crc(4) + csize(4) + usize(4)
            // + nameLen(2) + extraLen(2) + name + extra + filedata
            try out.writeLE(UInt32(0x04034b50))
            try out.writeLE(UInt16(20)) // version needed to extract
            try out.writeLE(UInt16(0))  // flags
            try out.writeLE(UInt16(0))  // compression = store
            try out.writeLE(UInt16(0))  // mod time
            try out.writeLE(UInt16(0))  // mod date
            try out.writeLE(info.crc32)
            try out.writeLE(size) // compressed size
            try out.writeLE(size) // uncompressed size
            try out.writeLE(UInt16(name.utf8.count))
            try out.writeLE(UInt16(0)) // extra len
            try out.write(contentsOf: name.data(using: .utf8)!)
            try out.writeFileData(from: fileURL)

            central.append(
                CentralDirectoryEntry(
                    name: name,
                    crc32: info.crc32,
                    compressedSize: size,
                    uncompressedSize: size,
                    localHeaderOffset: localOffset
                )
            )
        }

        let centralDirectoryOffset64 = try out.offset()
        guard centralDirectoryOffset64 <= UInt64(UInt32.max) else { throw ZipError.archiveTooLarge(zipURL) }
        let centralDirectoryOffset = UInt32(centralDirectoryOffset64)

        // Central directory records
        for entry in central {
            let nameData = entry.name.data(using: .utf8)!

            try out.writeLE(UInt32(0x02014b50)) // central file header signature
            try out.writeLE(UInt16(20)) // version made by
            try out.writeLE(UInt16(20)) // version needed to extract
            try out.writeLE(UInt16(0))  // flags
            try out.writeLE(UInt16(0))  // method store
            try out.writeLE(UInt16(0))  // mod time
            try out.writeLE(UInt16(0))  // mod date
            try out.writeLE(entry.crc32)
            try out.writeLE(entry.compressedSize)
            try out.writeLE(entry.uncompressedSize)
            try out.writeLE(UInt16(nameData.count))
            try out.writeLE(UInt16(0)) // extra len
            try out.writeLE(UInt16(0)) // comment len
            try out.writeLE(UInt16(0)) // disk number
            try out.writeLE(UInt16(0)) // internal attrs
            try out.writeLE(UInt32(0)) // external attrs
            try out.writeLE(entry.localHeaderOffset)
            try out.write(contentsOf: nameData)
        }

        let endOffset = try out.offset()
        guard endOffset <= UInt64(UInt32.max) else { throw ZipError.archiveTooLarge(zipURL) }
        let centralDirectorySize = UInt32(endOffset) - centralDirectoryOffset

        // End of central directory record
        try out.writeLE(UInt32(0x06054b50))
        try out.writeLE(UInt16(0)) // disk number
        try out.writeLE(UInt16(0)) // start disk
        try out.writeLE(UInt16(central.count))
        try out.writeLE(UInt16(central.count))
        try out.writeLE(centralDirectorySize)
        try out.writeLE(centralDirectoryOffset)
        try out.writeLE(UInt16(0)) // comment len
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

    static func checksumAndSize(_ url: URL) throws -> (crc32: UInt32, size: UInt64) {
        let handle = try FileHandle(forReadingFrom: url)
        defer { try? handle.close() }
        var crc: UInt32 = 0xFFFFFFFF
        var size: UInt64 = 0
        while let chunk = try handle.read(upToCount: 1024 * 1024), !chunk.isEmpty {
            size += UInt64(chunk.count)
            for b in chunk {
                let idx = Int((crc ^ UInt32(b)) & 0xFF)
                crc = table[idx] ^ (crc >> 8)
            }
        }
        return (crc ^ 0xFFFFFFFF, size)
    }
}

private extension FileHandle {
    func writeLE(_ v: UInt16) throws {
        var x = v.littleEndian
        let data = Swift.withUnsafeBytes(of: &x) { Data($0) }
        try write(contentsOf: data)
    }

    func writeLE(_ v: UInt32) throws {
        var x = v.littleEndian
        let data = Swift.withUnsafeBytes(of: &x) { Data($0) }
        try write(contentsOf: data)
    }

    func writeFileData(from url: URL) throws {
        let input = try FileHandle(forReadingFrom: url)
        defer { try? input.close() }
        while let chunk = try input.read(upToCount: 1024 * 1024), !chunk.isEmpty {
            try write(contentsOf: chunk)
        }
    }
}
