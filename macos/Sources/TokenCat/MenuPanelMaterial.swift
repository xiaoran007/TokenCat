import SwiftUI

/// One glass surface for the menu; usage rows remain on the content layer.
struct MenuPanelMaterial: ViewModifier {
    @Environment(\.accessibilityReduceTransparency) private var reduceTransparency
    @Environment(\.colorSchemeContrast) private var contrast

    @ViewBuilder
    func body(content: Content) -> some View {
        if reduceTransparency || contrast == .increased {
            content.background(Color(nsColor: .windowBackgroundColor))
        } else if #available(macOS 26.0, *) {
            content.background {
                Color.clear
                    .glassEffect(.regular, in: RoundedRectangle(cornerRadius: 20))
                    .allowsHitTesting(false)
            }
        } else {
            content.background(.regularMaterial)
        }
    }
}
