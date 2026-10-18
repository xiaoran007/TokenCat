import AppKit
import Combine
import SwiftUI
import TokenCatKit

@MainActor
final class DashboardWindowController: NSWindowController {
    private let settings: AppSettings
    private let model: AppModel
    private let settingsWindow: SettingsWindowController
    private var appearanceObserver: AnyCancellable?

    init(settings: AppSettings, model: AppModel, settingsWindow: SettingsWindowController) {
        self.settings = settings
        self.model = model
        self.settingsWindow = settingsWindow
        super.init(window: nil)
        appearanceObserver = settings.$language.combineLatest(settings.$appearance)
            .sink { [weak self] language, appearance in
                self?.updateWindow(language: language, appearance: appearance)
            }
    }

    @available(*, unavailable)
    required init?(coder: NSCoder) { fatalError("Dashboard windows are created programmatically.") }

    func open() {
        if window == nil {
            let size = NSSize(width: 1040, height: 720)
            let window = NSWindow(contentRect: NSRect(origin: .zero, size: size),
                                  styleMask: [.titled, .closable, .miniaturizable, .resizable],
                                  backing: .buffered, defer: false)
            let content = DashboardWindowContent(settings: settings, model: model, settingsWindow: settingsWindow)
            window.contentViewController = NSHostingController(rootView: content)
            window.setContentSize(size)
            window.contentMinSize = NSSize(width: 800, height: 560)
            window.identifier = NSUserInterfaceItemIdentifier("tokencat-dashboard")
            window.toolbarStyle = .unified
            window.center()
            self.window = window
            updateWindow(language: settings.language, appearance: settings.appearance)
        }
        NSApp.activate()
        showWindow(nil)
    }

    private func updateWindow(language: AppLanguage, appearance: String) {
        window?.title = Localizer(language).text("app.name")
        window?.appearance = appearance == "light" ? NSAppearance(named: .aqua)
            : appearance == "dark" ? NSAppearance(named: .darkAqua) : nil
    }
}

struct DashboardWindowContent: View {
    @ObservedObject var settings: AppSettings
    let model: AppModel
    let settingsWindow: SettingsWindowController

    var body: some View {
        DashboardView()
            .environmentObject(model)
            .environmentObject(settings)
            .environmentObject(settingsWindow)
            .environment(\.locale, settings.language.locale)
            .transformEnvironment(\.timeZone) { timeZone in
                if let configuredTimeZone = settings.timeZone { timeZone = configuredTimeZone }
            }
            .tint(TokenCatTheme.accent)
            .preferredColorScheme(settings.colorScheme)
    }
}
