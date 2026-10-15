import SwiftUI

enum MenuPanelStyle: String, CaseIterable, Identifiable {
    case system, cards

    var id: Self { self }
    var localizationKey: String { "menuStyle.\(rawValue)" }
}

/// Glass belongs to separate modules, while MenuBarExtra owns the window surface.
struct MenuSectionSurface: ViewModifier {
    var padding: CGFloat = 16
    var cornerRadius: CGFloat = 18
    @EnvironmentObject private var settings: AppSettings
    @Environment(\.accessibilityReduceTransparency) private var reduceTransparency
    @Environment(\.colorSchemeContrast) private var contrast

    @ViewBuilder
    func body(content: Content) -> some View {
        if settings.menuStyle == .cards {
            let shape = RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
            if reduceTransparency || contrast == .increased {
                content.padding(padding)
                    .background(Color(nsColor: .controlBackgroundColor), in: shape)
                    .overlay(shape.strokeBorder(.primary.opacity(0.25), lineWidth: 1))
            } else if #available(macOS 26.0, *) {
                content.padding(padding).glassEffect(.regular, in: shape)
            } else {
                content.padding(padding).background(.regularMaterial, in: shape)
            }
        } else {
            content
        }
    }
}

struct MenuSection<Content: View>: View {
    private let content: Content

    init(@ViewBuilder content: () -> Content) { self.content = content() }

    var body: some View {
        content.frame(maxWidth: .infinity, alignment: .leading)
            .modifier(MenuSectionSurface())
    }
}

struct MenuModuleContainer<Content: View>: View {
    @EnvironmentObject private var settings: AppSettings
    let content: Content

    init(@ViewBuilder content: () -> Content) { self.content = content() }

    @ViewBuilder
    var body: some View {
        if #available(macOS 26.0, *), settings.menuStyle == .cards {
            GlassEffectContainer(spacing: 8) { content }
        } else {
            content
        }
    }
}
