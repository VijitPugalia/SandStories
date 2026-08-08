import CoreLocation
import Foundation
import SwiftUI

actor LocationFileWriter {
    struct SessionLocation: Codable, Sendable {
        let capturedAt: TimeInterval
        let latitude: Double
        let longitude: Double
        let altitude: Double?
    }

    func writeSessionLocation(_ location: SessionLocation) async throws {
        let documentsURL = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask).first!
        let url = documentsURL.appendingPathComponent("session_location.json")

        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .withoutEscapingSlashes]
        let data = try encoder.encode(location)
        try data.write(to: url, options: [.atomic])
    }
}

@MainActor
final class LocationCaptureManager: NSObject, ObservableObject, @preconcurrency CLLocationManagerDelegate {
    @Published private(set) var coordinateDisplay: String = "Location: --"

    private let locationManager = CLLocationManager()
    private let fileWriter = LocationFileWriter()

    private var sessionStartTime: TimeInterval = 0
    private var didPersistSessionLocation = false
    private var sessionLocation: LocationFileWriter.SessionLocation?
    private var authorizationContinuation: CheckedContinuation<CLAuthorizationStatus, Never>?

    override init() {
        super.init()
        locationManager.delegate = self
        locationManager.desiredAccuracy = kCLLocationAccuracyBest
    }

    /// Requests one fresh fix per capture session. Continuous GPS updates are unnecessary heat.
    func startCapture() async {
        sessionStartTime = Date().timeIntervalSince1970
        didPersistSessionLocation = false
        sessionLocation = nil
        coordinateDisplay = "Location: requesting..."

        let status = await ensureAuthorization()
        switch status {
        case .authorizedAlways, .authorizedWhenInUse:
            locationManager.requestLocation()
        default:
            coordinateDisplay = "Location: unavailable (permission not granted)"
        }
    }

    func stopCapture() {
        locationManager.stopUpdatingLocation()
    }

    private func ensureAuthorization() async -> CLAuthorizationStatus {
        let currentStatus = locationManager.authorizationStatus
        switch currentStatus {
        case .authorizedAlways, .authorizedWhenInUse:
            return currentStatus
        case .denied, .restricted:
            return currentStatus
        case .notDetermined:
            return await withCheckedContinuation { continuation in
                authorizationContinuation = continuation
                locationManager.requestWhenInUseAuthorization()
            }
        @unknown default:
            return currentStatus
        }
    }

    private func updateDisplay(with location: CLLocation) {
        let lat = location.coordinate.latitude
        let lon = location.coordinate.longitude
        let alt = location.altitude

        if alt.isFinite && alt > -1000 {
            coordinateDisplay = String(format: "Lat: %.5f  Lon: %.5f  Alt: %.1fm", lat, lon, alt)
        } else {
            coordinateDisplay = String(format: "Lat: %.5f  Lon: %.5f", lat, lon)
        }
    }

    func locationManager(_ manager: CLLocationManager, didChangeAuthorization status: CLAuthorizationStatus) {
        handleAuthorizationStatus(status)
    }

    func locationManagerDidChangeAuthorization(_ manager: CLLocationManager) {
        handleAuthorizationStatus(manager.authorizationStatus)
    }

    private func handleAuthorizationStatus(_ status: CLAuthorizationStatus) {
        if let continuation = authorizationContinuation {
            authorizationContinuation = nil
            continuation.resume(returning: status)
        }
    }

    func locationManager(_ manager: CLLocationManager, didUpdateLocations locations: [CLLocation]) {
        guard let location = locations.last, location.horizontalAccuracy >= 0 else { return }

        locationManager.stopUpdatingLocation()
        updateDisplay(with: location)

        guard !didPersistSessionLocation else { return }
        didPersistSessionLocation = true
        let persisted = LocationFileWriter.SessionLocation(
            capturedAt: sessionStartTime,
            latitude: location.coordinate.latitude,
            longitude: location.coordinate.longitude,
            altitude: (location.altitude.isFinite && location.altitude > -1000) ? location.altitude : nil
        )
        sessionLocation = persisted
        Task {
            try? await fileWriter.writeSessionLocation(persisted)
        }
    }

    func locationManager(_ manager: CLLocationManager, didFailWithError error: Error) {
        locationManager.stopUpdatingLocation()
        coordinateDisplay = "Location: unavailable (\(error.localizedDescription))"
    }

    func getSessionLocation() -> LocationFileWriter.SessionLocation? {
        sessionLocation
    }
}