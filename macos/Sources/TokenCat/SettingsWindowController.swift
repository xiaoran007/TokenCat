import AppKit
import Combine
import SwiftUI
import TokenCatKit

@MainActor
final class SettingsWindowController: NSWindowController, ObservableObject {
    private let settings: AppSettings
    private let model: AppModel
    private var appearanceObserver: AnyCancellable?

    init(settings: AppSettings, model: AppModel) {
        self.settings = settings
        self.model = model
        super.init(window: nil)
        appearanceObserver = settings.$language.combineLatest(settings.$appearance)
            .sink { [weak self] language, appearance in
                self?.updateWindow(language: language, appearance: appearance)
            }
    }

    @available(*, unavailable)
    required init?(coder: NSCoder) { fatalError("Settings windows are created programmatically.") }

    func open() {
        if window == nil {
            let content = SettingsWindowContent(settings: settings, model: model)
            let size = NSSize(width: 590, height: 520)
            let window = NSWindow(contentRect: NSRect(origin: .zero, size: size),
                                  styleMask: [.titled, .closable], backing: .buffered, defer: false)
            let host = NSHostingController(rootView: content)
            host.view.setFrameSize(size)
            window.contentViewController = host
            window.identifier = NSUserInterfaceItemIdentifier("tokencat-settings")
            window.center()
            self.window = window
            updateWindow(language: settings.language, appearance: settings.appearance)
        }
        NSApp.activate()
        showWindow(nil)
    }

    private func updateWindow(language: AppLanguage, appearance: String) {
        window?.title = Localizer(language).text("settings.title")
        window?.appearance = appearance == "light" ? NSAppearance(named: .aqua)
            : appearance == "dark" ? NSAppearance(named: .darkAqua) : nil
    }
}

struct SettingsWindowContent: View {
    @ObservedObject var settings: AppSettings
    let model: AppModel

    var body: some View {
        SettingsView()
            .environmentObject(model)
            .environmentObject(settings)
            .environment(\.locale, settings.language.locale)
            .tint(TokenCatTheme.accent)
            .preferredColorScheme(settings.colorScheme)
    }
}
