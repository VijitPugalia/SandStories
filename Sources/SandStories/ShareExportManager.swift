import Foundation

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
}

