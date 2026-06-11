import SwiftUI
import UIKit

// MARK: - UIVisualEffectView bridge (HIG glass / materials)

struct VisualEffectBlur: UIViewRepresentable {
    var style: UIBlurEffect.Style = .systemUltraThinMaterial

    func makeUIView(context: Context) -> UIVisualEffectView {
        let view = UIVisualEffectView(effect: UIBlurEffect(style: style))
        view.backgroundColor = .clear
        return view
    }

    func updateUIView(_ uiView: UIVisualEffectView, context: Context) {
        uiView.effect = UIBlurEffect(style: style)
    }
}

// MARK: - Glass panel (frosted + adaptive gradient border + soft shadow)

struct GlassPanelShape: Shape {
    var cornerRadius: CGFloat = 20

    func path(in rect: CGRect) -> Path {
        RoundedRectangle(cornerRadius: cornerRadius, style: .continuous).path(in: rect)
    }
}

struct GlassPanelModifier: ViewModifier {
    var cornerRadius: CGFloat
    var blurStyle: UIBlurEffect.Style
    var shadowRadius: CGFloat
    var shadowYOffset: CGFloat

    @Environment(\.colorScheme) var colorScheme

    func body(content: Content) -> some View {
        content
            .background {
                ZStack {
                    VisualEffectBlur(style: blurStyle)
                    // Premium frosted glass tint
                    Color.white.opacity(colorScheme == .dark ? 0.03 : 0.08)
                }
                .clipShape(GlassPanelShape(cornerRadius: cornerRadius))
            }
            .overlay {
                // Outer specular border
                GlassPanelShape(cornerRadius: cornerRadius)
                    .stroke(
                        LinearGradient(
                            colors: colorScheme == .dark ? [
                                Color.white.opacity(0.24),
                                Color.white.opacity(0.04),
                                Color.black.opacity(0.25),
                                Color.white.opacity(0.1)
                            ] : [
                                Color.white.opacity(0.55),
                                Color.white.opacity(0.12),
                                Color.black.opacity(0.08),
                                Color.white.opacity(0.2)
                            ],
                            startPoint: .topLeading,
                            endPoint: .bottomTrailing
                        ),
                        lineWidth: 1
                    )
            }
            .overlay {
                // Inner highlight stroke for liquid refraction/bevel
                GlassPanelShape(cornerRadius: cornerRadius)
                    .stroke(
                        LinearGradient(
                            colors: colorScheme == .dark ? [
                                Color.white.opacity(0.15),
                                Color.clear,
                                Color.clear,
                                Color.clear
                            ] : [
                                Color.white.opacity(0.40),
                                Color.clear,
                                Color.clear,
                                Color.clear
                            ],
                            startPoint: .topLeading,
                            endPoint: .bottomTrailing
                        ),
                        lineWidth: 2
                    )
                    .padding(1)
            }
            .shadow(
                color: Color.black.opacity(colorScheme == .dark ? 0.25 : 0.08),
                radius: shadowRadius,
                x: 0,
                y: shadowYOffset
            )
    }
}

extension View {
    /// Frosted glass surface with subtle border and drop shadow (semantic colors).
    func glassPanel(
        cornerRadius: CGFloat = 20,
        blurStyle: UIBlurEffect.Style = .systemUltraThinMaterial,
        shadowRadius: CGFloat = 14,
        shadowYOffset: CGFloat = 6
    ) -> some View {
        self.modifier(
            GlassPanelModifier(
                cornerRadius: cornerRadius,
                blurStyle: blurStyle,
                shadowRadius: shadowRadius,
                shadowYOffset: shadowYOffset
            )
        )
    }
}
