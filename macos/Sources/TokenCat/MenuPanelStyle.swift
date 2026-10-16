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

    func body(content: Content) -> some View {
        content
            .padding(settings.menuStyle == .cards ? padding : 0)
            .background { surface }
    }

    @ViewBuilder
    private var surface: some View {
        if settings.menuStyle == .cards {
            let shape = RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
            if reduceTransparency || contrast == .increased {
                shape.fill(Color(nsColor: .controlBackgroundColor))
                    .overlay(shape.strokeBorder(.primary.opacity(0.25), lineWidth: 1))
            } else if #available(macOS 26.0, *) {
                shape.fill(.clear).glassEffect(.regular, in: shape)
            } else {
                shape.fill(.regularMaterial)
            }
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
    let content: Content

    init(@ViewBuilder content: () -> Content) { self.content = content() }

    @ViewBuilder
    var body: some View {
        if #available(macOS 26.0, *) {
            GlassEffectContainer(spacing: 8) { content }
        } else {
            content
        }
    }
}
