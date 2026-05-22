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

// MARK: - Glass panel (frosted + 1pt ~20% border + soft shadow)

struct GlassPanelShape: Shape {
    var cornerRadius: CGFloat = 20

    func path(in rect: CGRect) -> Path {
        RoundedRectangle(cornerRadius: cornerRadius, style: .continuous).path(in: rect)
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
        self
            .background {
                VisualEffectBlur(style: blurStyle)
                    .clipShape(GlassPanelShape(cornerRadius: cornerRadius))
            }
            .overlay {
                GlassPanelShape(cornerRadius: cornerRadius)
                    .stroke(Color(uiColor: .label).opacity(0.2), lineWidth: 1)
            }
            .shadow(
                color: Color(uiColor: .label).opacity(0.12),
                radius: shadowRadius,
                x: 0,
                y: shadowYOffset
            )
    }
}
