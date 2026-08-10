import SwiftUI

struct CameraZoomRail: View {
    @ObservedObject var zoomController: CameraZoomController
    let isRecording: Bool

    var body: some View {
        VStack(spacing: 2) {
            HStack(spacing: 14) {
                ForEach(ZoomPreset.allCases) { preset in
                    zoomButton(for: preset)
                }
            }
            .padding(.horizontal, 8)
            .frame(height: 56)

            Text(zoomController.lastAppliedSummary)
                .font(.system(size: 10, weight: .medium, design: .monospaced))
                .foregroundStyle(Color.white.opacity(0.72))
                .lineLimit(1)
                .minimumScaleFactor(0.72)
                .accessibilityLabel("Applied camera: \(zoomController.lastAppliedSummary)")
        }
        .frame(height: 72)
        .accessibilityElement(children: .contain)
        .accessibilityLabel("RGB camera zoom")
    }

    private func zoomButton(for preset: ZoomPreset) -> some View {
        let isSelected = zoomController.selectedPreset == preset
        let isSupported = zoomController.supportedPresets.contains(preset)

        return Button {
            zoomController.select(preset)
        } label: {
            Text(preset.title)
                .font(.system(size: 19, weight: isSelected ? .medium : .regular, design: .rounded))
                .monospacedDigit()
                .foregroundStyle(isSelected ? Color.yellow : Color.white)
                .frame(width: 52, height: 52)
                .background {
                    Circle()
                        .fill(isSelected ? Color.black.opacity(0.42) : Color.clear)
                }
                .contentShape(Circle())
        }
        .buttonStyle(.plain)
        .disabled(!isSupported)
        .opacity(isSupported ? 1 : 0.32)
        .animation(.easeOut(duration: 0.12), value: isSelected)
        .accessibilityLabel("\(preset.title) RGB zoom")
        .accessibilityHint(
            isRecording
                ? "Changes the RGB camera view while recording. LiDAR depth is unchanged."
                : "Changes the RGB camera view. LiDAR depth is unchanged."
        )
        .accessibilityAddTraits(isSelected ? .isSelected : [])
    }
}
