import Foundation
import CryptoKit

actor ShareExportManager {
    struct GeoJSONFeatureCollection: Codable, Sendable {
        let type: String = "FeatureCollection"
        let features: [GeoJSONFeature]

        enum CodingKeys: String, CodingKey {
            case type, features
        }
    }

    struct GeoJSONFeature: Codable, Sendable {
        let type: String = "Feature"
        let geometry: GeoJSONGeometry
        let properties: [String: GeoJSONPropertyValue]

        enum CodingKeys: String, CodingKey {
            case type, geometry, properties
        }
    }

    struct GeoJSONGeometry: Codable, Sendable {
        let type: String = "LineString"
        let coordinates: [[Double]]

        enum CodingKeys: String, CodingKey {
            case type, coordinates
        }
    }

    enum GeoJSONPropertyValue: Codable, Sendable {
        case string(String)
        case number(Double)
        case null

        init(from decoder: Decoder) throws {
            let container = try decoder.singleValueContainer()
            if container.decodeNil() {
                self = .null
            } else if let n = try? container.decode(Double.self) {
                self = .number(n)
            } else if let s = try? container.decode(String.self) {
                self = .string(s)
            } else {
                self = .null
            }
        }

        func encode(to encoder: Encoder) throws {
            var container = encoder.singleValueContainer()
            switch self {
            case .string(let s):
                try container.encode(s)
            case .number(let n):
                try container.encode(n)
            case .null:
                try container.encodeNil()
            }
        }
    }

    func exportGeoJSON(
        strokes: [StrokeRecorder.Stroke],
        sessionLocation: LocationFileWriter.SessionLocation?
    ) async throws -> URL {
        let docs = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask).first!
        let url = docs.appendingPathComponent("strokes_session.geojson")

        let propertiesBase: [String: GeoJSONPropertyValue] = [
            "session_latitude": sessionLocation.map { .number($0.latitude) } ?? .null,
            "session_longitude": sessionLocation.map { .number($0.longitude) } ?? .null,
            "session_altitude": sessionLocation.flatMap { $0.altitude }.map { .number($0) } ?? .null,
        ]

        let features: [GeoJSONFeature] = strokes.map { stroke in
            let coords: [[Double]] = stroke.points.map { p in
                [Double(p.x), Double(p.y), Double(p.z)]
            }

            var props = propertiesBase
            props["stroke_startedAt"] = .number(stroke.startedAt)
            props["stroke_finishedAt"] = .number(stroke.finishedAt)

            return GeoJSONFeature(
                geometry: GeoJSONGeometry(coordinates: coords),
                properties: props
            )
        }

        let fc = GeoJSONFeatureCollection(features: features)
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .withoutEscapingSlashes]
        let data = try encoder.encode(fc)
        try data.write(to: url, options: [.atomic])
        return url
    }

    func exportDepthZip() async throws -> URL {
        let fm = FileManager.default
        let docs = fm.urls(for: .documentDirectory, in: .userDomainMask).first!
        let zipURL = docs.appendingPathComponent("depth_maps.zip")

        if fm.fileExists(atPath: zipURL.path) {
            try? fm.removeItem(at: zipURL)
        }

        let files = try fm.contentsOfDirectory(at: docs, includingPropertiesForKeys: nil)
            .filter { $0.lastPathComponent.hasPrefix("depth_") && $0.pathExtension.lowercased() == "png" }

        let writer = SimpleZipWriter()
        try writer.writeZip(storingFiles: files, to: zipURL)

        return zipURL
    }

    /// Zips a packaged session folder (`manifest.json`, depth/, rgb/, etc.) for sharing.
    func zipSessionFolder(_ sessionFolder: URL) async throws -> URL {
        // Generate RO-Crate metadata inside the session folder before zipping
        try? await writeROCrateMetadata(for: sessionFolder)

        let fm = FileManager.default
        let docs = fm.urls(for: .documentDirectory, in: .userDomainMask).first!
        let zipName = sessionFolder.lastPathComponent + ".zip"
        let zipURL = docs.appendingPathComponent(zipName)
        if fm.fileExists(atPath: zipURL.path) {
            try? fm.removeItem(at: zipURL)
        }
        let writer = SimpleZipWriter()
        try writer.writeZip(storingDirectoryTree: sessionFolder, to: zipURL)
        return zipURL
    }

    private func sha256(for fileURL: URL) -> String {
        do {
            let handle = try FileHandle(forReadingFrom: fileURL)
            defer { try? handle.close() }
            var hasher = SHA256()
            while let chunk = try handle.read(upToCount: 64 * 1024), !chunk.isEmpty {
                hasher.update(data: chunk)
            }
            let digest = hasher.finalize()
            return digest.map { String(format: "%02hhx", $0) }.joined()
        } catch {
            return ""
        }
    }

    private func writeROCrateMetadata(for sessionFolder: URL) async throws {
        let fm = FileManager.default
        let relativePaths = try fm.subpathsOfDirectory(atPath: sessionFolder.path)
        
        var filesMetadata: [[String: Any]] = []
        var hasPartIds: [[String: String]] = []
        
        let df = ISO8601DateFormatter()
        let currentDateStr = df.string(from: Date())
        
        var sessionName = "SandStories Session - " + sessionFolder.lastPathComponent
        var sessionId = sessionFolder.lastPathComponent
        var schemaVersion = 1
        var modalities: [String] = ["strokes"]
        
        let manifestURL = sessionFolder.appendingPathComponent("manifest.json")
        if let manifestData = try? Data(contentsOf: manifestURL),
           let manifestJson = try? JSONSerialization.jsonObject(with: manifestData) as? [String: Any] {
            if let id = manifestJson["sessionId"] as? String {
                sessionId = id
            }
            if let sv = manifestJson["schemaVersion"] as? Int {
                schemaVersion = sv
            }
            if let depthFrames = manifestJson["depthFrames"] as? [[String: Any]], !depthFrames.isEmpty {
                modalities.append("depth")
            }
            if let rgbFrames = manifestJson["rgbFrames"] as? [[String: Any]], !rgbFrames.isEmpty {
                modalities.append("rgb")
            }
            if manifestJson["audio"] != nil {
                modalities.append("audio")
            }
            if manifestJson["trayBoundary"] != nil {
                modalities.append("boundary")
            }
            if manifestJson["objectDetectionsFile"] != nil {
                modalities.append("objects")
            }
            sessionName = "SandStories Session - \(sessionId)"
        }
        
        for relPath in relativePaths.sorted() {
            let fileURL = sessionFolder.appendingPathComponent(relPath)
            var isDir: ObjCBool = false
            guard fm.fileExists(atPath: fileURL.path, isDirectory: &isDir), !isDir.boolValue else {
                continue
            }
            
            if relPath == "ro-crate-metadata.json" {
                continue
            }
            
            let fileHash = sha256(for: fileURL)
            let ext = fileURL.pathExtension.lowercased()
            let mimeType: String
            switch ext {
            case "json": mimeType = "application/json"
            case "jsonl": mimeType = "application/x-ndjson"
            case "png": mimeType = "image/png"
            case "jpg", "jpeg": mimeType = "image/jpeg"
            case "m4a": mimeType = "audio/x-m4a"
            default: mimeType = "application/octet-stream"
            }
            
            let fileMeta: [String: Any] = [
                "@id": relPath,
                "@type": "File",
                "name": fileURL.lastPathComponent,
                "encodingFormat": mimeType,
                "sha256": fileHash
            ]
            filesMetadata.append(fileMeta)
            hasPartIds.append(["@id": relPath])
        }
        
        let rootDataset: [String: Any] = [
            "@id": "./",
            "@type": "Dataset",
            "name": sessionName,
            "description": "Multimodal capture session data package for SandStories.",
            "creator": [
                "@type": "Person",
                "name": "SandStories Operator"
            ],
            "datePublished": currentDateStr,
            "license": "https://creativecommons.org/licenses/by/4.0/",
            "schemaVersion": schemaVersion,
            "modalities": modalities,
            "timestampSemantics": "ContinuousClock",
            "hasPart": hasPartIds
        ]
        
        let descriptor: [String: Any] = [
            "@id": "ro-crate-metadata.json",
            "@type": "CreativeWork",
            "conformsTo": ["@id": "https://w3id.org/ro/crate/1.1"],
            "about": ["@id": "./"]
        ]
        
        var graph: [[String: Any]] = [descriptor, rootDataset]
        graph.append(contentsOf: filesMetadata)
        
        let roCrate: [String: Any] = [
            "@context": "https://w3id.org/ro/crate/1.1/context",
            "@graph": graph
        ]
        
        let roCrateURL = sessionFolder.appendingPathComponent("ro-crate-metadata.json")
        let roCrateData = try JSONSerialization.data(withJSONObject: roCrate, options: [.prettyPrinted, .sortedKeys])
        try roCrateData.write(to: roCrateURL, options: [.atomic])
    }
}

