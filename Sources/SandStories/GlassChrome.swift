import SwiftUI
import UIKit

// Kept for compatibility with older sheets; capture chrome uses static fills to avoid live blur work.
struct VisualEffectBlur: UIViewRepresentable {
    var style: UIBlurEffect.Style = .systemUltraThinMaterial

    func makeUIView(context: Context) -> UIVisualEffectView {
        let view = UIVisualEffectView(effect: UIBlurEffect(style: style))
        view.backgroundColor = .clear
        return view
    }

    func updateUIView(_ uiView: UIVisualEffectView, context: Context) {
        guard uiView.effect == nil else { return }
        uiView.effect = UIBlurEffect(style: style)
    }
}

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

    func body(content: Content) -> some View {
        content
            .background {
                GlassPanelShape(cornerRadius: cornerRadius)
                    .fill(Color.black.opacity(0.52))
            }
            .overlay {
                GlassPanelShape(cornerRadius: cornerRadius)
                    .stroke(Color.white.opacity(0.16), lineWidth: 0.75)
            }
            .shadow(
                color: Color.black.opacity(0.16),
                radius: min(shadowRadius, 4),
                x: 0,
                y: min(shadowYOffset, 2)
            )
    }
}

struct LiquidGlassDockModifier: ViewModifier {
    func body(content: Content) -> some View {
        content
            .background {
                Capsule(style: .continuous)
                    .fill(Color.black.opacity(0.68))
                    .overlay {
                        Capsule(style: .continuous)
                            .stroke(Color.white.opacity(0.17), lineWidth: 0.75)
                    }
            }
            .shadow(color: Color.black.opacity(0.18), radius: 4, x: 0, y: 2)
    }
}

extension View {
    func liquidGlassDock() -> some View {
        modifier(LiquidGlassDockModifier())
    }

    func glassPanel(
        cornerRadius: CGFloat = 20,
        blurStyle: UIBlurEffect.Style = .systemUltraThinMaterial,
        shadowRadius: CGFloat = 14,
        shadowYOffset: CGFloat = 6
    ) -> some View {
        modifier(
            GlassPanelModifier(
                cornerRadius: cornerRadius,
                blurStyle: blurStyle,
                shadowRadius: shadowRadius,
                shadowYOffset: shadowYOffset
            )
        )
    }
}