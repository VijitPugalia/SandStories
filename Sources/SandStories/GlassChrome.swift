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
                GlassPanelShape(cornerRadius: cornerRadius)
                    .stroke(
                        LinearGradient(
                            colors: colorScheme == .dark ? [
                                Color.white.opacity(0.22),
                                Color.white.opacity(0.03),
                                Color.black.opacity(0.2),
                                Color.white.opacity(0.08)
                            ] : [
                                Color.white.opacity(0.45),
                                Color.white.opacity(0.1),
                                Color.black.opacity(0.06),
                                Color.white.opacity(0.15)
                            ],
                            startPoint: .topLeading,
                            endPoint: .bottomTrailing
                        ),
                        lineWidth: 1
                    )
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
