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

    private var didStartCapture = false
    private var sessionStartTime: TimeInterval = 0
    private var didPersistSessionLocation = false
    private var sessionLocation: LocationFileWriter.SessionLocation?

    private var authorizationContinuation: CheckedContinuation<CLAuthorizationStatus, Never>?
    private var firstLocationContinuation: CheckedContinuation<CLLocation, Never>?

    override init() {
        super.init()
        locationManager.delegate = self
        locationManager.desiredAccuracy = kCLLocationAccuracyBest
    }

    func startCapture() async {
        guard !didStartCapture else { return }
        didStartCapture = true
        sessionStartTime = Date().timeIntervalSince1970

        // Kick off permission flow and wait until we have the first coordinate fix.
        coordinateDisplay = "Location: requesting..."
        let status = await ensureAuthorization()
        switch status {
        case .authorizedAlways, .authorizedWhenInUse:
            locationManager.startUpdatingLocation()
            _ = await waitForFirstLocation()
        default:
            coordinateDisplay = "Location: unavailable (permission not granted)"
        }
    }

    private func ensureAuthorization() async -> CLAuthorizationStatus {
        let currentStatus = locationManager.authorizationStatus
        switch currentStatus {
        case .authorizedAlways, .authorizedWhenInUse:
            return currentStatus
        case .denied, .restricted:
            return currentStatus
        case .notDetermined:
            return await withCheckedContinuation { cont in
                authorizationContinuation = cont
                locationManager.requestWhenInUseAuthorization()
            }
        @unknown default:
            return currentStatus
        }
    }

    private func waitForFirstLocation() async -> CLLocation? {
        await withCheckedContinuation { cont in
            firstLocationContinuation = cont
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
        if let cont = authorizationContinuation {
            authorizationContinuation = nil
            cont.resume(returning: status)
        }
    }

    func locationManager(_ manager: CLLocationManager, didUpdateLocations locations: [CLLocation]) {
        guard let location = locations.last else { return }

        updateDisplay(with: location)

        if !didPersistSessionLocation {
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

        if let cont = firstLocationContinuation {
            firstLocationContinuation = nil
            cont.resume(returning: location)
        }
    }

    func locationManager(_ manager: CLLocationManager, didFailWithError error: Error) {
        coordinateDisplay = "Location: unavailable (\(error.localizedDescription))"

        if let cont = firstLocationContinuation {
            firstLocationContinuation = nil
            // Resume with a dummy location isn't helpful; just resume with a non-nil sentinel isn't possible.
            // Instead, stop waiting by resuming with a zero coordinate.
            cont.resume(returning: CLLocation(latitude: 0, longitude: 0))
        }
    }

    func getSessionLocation() -> LocationFileWriter.SessionLocation? {
        sessionLocation
    }
}

