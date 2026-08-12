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

/// Panel chrome. On iOS 26 this is real Liquid Glass (adaptive material that
/// samples the content beneath it); on older systems it falls back to the
/// static dark fill used previously.
struct GlassPanelModifier: ViewModifier {
    var cornerRadius: CGFloat
    var blurStyle: UIBlurEffect.Style
    var shadowRadius: CGFloat
    var shadowYOffset: CGFloat

    @ViewBuilder
    func body(content: Content) -> some View {
        if #available(iOS 26.0, *) {
            content
                .glassEffect(.regular, in: .rect(cornerRadius: cornerRadius, style: .continuous))
        } else {
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
}

/// Capsule chrome for docks and status pills. Real Liquid Glass on iOS 26.
struct LiquidGlassDockModifier: ViewModifier {
    @ViewBuilder
    func body(content: Content) -> some View {
        if #available(iOS 26.0, *) {
            content
                .glassEffect(.regular, in: .capsule)
        } else {
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
}

/// Circular control chrome. On iOS 26 the glass is interactive: it scales,
/// bounces, and shimmers on touch, matching system toolbar buttons.
struct InteractiveGlassCircleModifier: ViewModifier {
    var fallbackFillOpacity: Double

    @ViewBuilder
    func body(content: Content) -> some View {
        if #available(iOS 26.0, *) {
            content
                .glassEffect(.regular.interactive(), in: .circle)
        } else {
            content
                .background {
                    Circle()
                        .fill(Color.black.opacity(fallbackFillOpacity))
                }
                .overlay {
                    Circle()
                        .stroke(Color.white.opacity(0.16), lineWidth: 0.75)
                }
        }
    }
}

extension View {
    func liquidGlassDock() -> some View {
        modifier(LiquidGlassDockModifier())
    }

    func interactiveGlassCircle(fallbackFillOpacity: Double = 0.52) -> some View {
        modifier(InteractiveGlassCircleModifier(fallbackFillOpacity: fallbackFillOpacity))
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
