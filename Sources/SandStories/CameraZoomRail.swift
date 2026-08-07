import SwiftUI

struct CameraZoomRail: View {
    @ObservedObject var zoomController: CameraZoomController
    let isRecording: Bool

    private var hidesZoomPresets: Bool {
        isRecording && zoomController.isLocked
    }

    var body: some View {
        VStack(spacing: 3) {
            HStack(spacing: 6) {
                Button {
                    guard !isRecording else { return }
                    zoomController.setLocked(!zoomController.isLocked)
                } label: {
                    Image(systemName: zoomController.isLocked ? "lock.fill" : "lock.open")
                        .font(.system(size: 14, weight: .semibold))
                        .foregroundStyle(zoomController.isLocked ? Color.yellow : Color.white)
                        .frame(width: 40, height: 40)
                        .background {
                            Circle()
                                .fill(Color.white.opacity(zoomController.isLocked ? 0.13 : 0.07))
                        }
                }
                .buttonStyle(.plain)
                .disabled(isRecording)
                .accessibilityLabel(zoomController.isLocked ? "Unlock camera lens" : "Lock camera lens")
                .accessibilityHint("Lock the selected physical camera before recording.")

                if !hidesZoomPresets {
                    Rectangle()
                        .fill(Color.white.opacity(0.16))
                        .frame(width: 1, height: 24)
                        .padding(.horizontal, 1)

                    ForEach(ZoomPreset.allCases) { preset in
                        zoomButton(for: preset)
                    }
                }
            }
            .animation(.easeOut(duration: 0.16), value: hidesZoomPresets)

            if !hidesZoomPresets {
                Text("RGB: \(zoomController.activeLensDescription) · LiDAR unchanged")
                    .font(.system(size: 10, weight: .medium, design: .rounded))
                    .foregroundStyle(Color.white.opacity(0.64))
                    .lineLimit(1)
                    .accessibilityLabel("RGB camera \(zoomController.activeLensDescription). LiDAR zoom is unchanged.")
            }
        }
        .padding(.horizontal, 8)
        .padding(.vertical, 6)
        .background {
            Capsule(style: .continuous)
                .fill(Color.black.opacity(0.76))
        }
        .overlay {
            Capsule(style: .continuous)
                .stroke(Color.white.opacity(0.17), lineWidth: 0.75)
        }
        .shadow(color: Color.black.opacity(0.18), radius: 4, y: 2)
    }

    private func zoomButton(for preset: ZoomPreset) -> some View {
        let isSelected = zoomController.selectedPreset == preset
        let isSupported = zoomController.supportedPresets.contains(preset)

        return Button {
            zoomController.select(preset)
        } label: {
            Text(preset.title)
                .font(.system(size: 14, weight: .semibold, design: .rounded))
                .monospacedDigit()
                .foregroundStyle(isSelected ? Color.black : Color.white)
                .frame(width: 40, height: 40)
                .background {
                    Circle()
                        .fill(isSelected ? Color.yellow : Color.clear)
                }
        }
        .buttonStyle(.plain)
        .disabled(!isSupported)
        .opacity(isSupported ? 1 : 0.28)
        .accessibilityLabel("\(preset.title) RGB zoom")
        .accessibilityAddTraits(isSelected ? .isSelected : [])
    }
}
