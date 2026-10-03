import AppKit
import SwiftUI

@MainActor
enum TokenCatBrand {
    static let mark = image(named: "TokenCatMark")

    static let menuMark: NSImage = {
        let menuImage = image(named: "TokenCatMenuMark")
        menuImage.isTemplate = true
        menuImage.size = NSSize(width: 22, height: 18.5625)
        return menuImage
    }()

    private static func image(named name: String) -> NSImage {
        guard let url = Bundle.module.url(forResource: name, withExtension: "pdf"),
              let image = NSImage(contentsOf: url) else {
            preconditionFailure("Missing or invalid bundled logo: \(name).pdf")
        }
        return image
    }
}

struct TokenCatLogo: View {
    var size: CGFloat = 24

    var body: some View {
        Image(nsImage: TokenCatBrand.mark)
            .renderingMode(.template)
            .resizable()
            .scaledToFit()
            .frame(width: size, height: size)
            .foregroundStyle(TokenCatTheme.accent)
            .accessibilityHidden(true)
    }
}
