import AppKit
import Combine
import TokenCatKit

@main
@MainActor
final class TokenCatApp: NSObject, NSApplicationDelegate {
    private lazy var settings = AppSettings()
    private lazy var model = AppModel(settings: settings)
    private lazy var settingsWindow = SettingsWindowController(settings: settings, model: model)
    private lazy var dashboardWindow = DashboardWindowController(settings: settings, model: model, settingsWindow: settingsWindow)
    private lazy var menuBar = MenuBarController(settings: settings, model: model, settingsWindow: settingsWindow) { [weak self] in
        self?.dashboardWindow.open()
    }
    private var languageObserver: AnyCancellable?

    static func main() {
        let application = NSApplication.shared
        let delegate = TokenCatApp()
        application.setActivationPolicy(.accessory)
        application.delegate = delegate
        withExtendedLifetime(delegate) { application.run() }
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        languageObserver = settings.$language.sink { [weak self] language in
            self?.configureMainMenu(language: language)
        }
        menuBar.start()
        model.start()
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { false }

    func applicationWillTerminate(_ notification: Notification) { menuBar.stop() }

    @objc private func openSettings() { settingsWindow.open() }

    private func configureMainMenu(language: AppLanguage) {
        let strings = Localizer(language)
        let main = NSMenu()
        let applicationItem = NSMenuItem()
        let applicationMenu = NSMenu(title: strings.text("app.name"))
        let settingsItem = NSMenuItem(title: strings.text("action.settings"), action: #selector(openSettings), keyEquivalent: ",")
        settingsItem.target = self
        applicationMenu.addItem(settingsItem)
        applicationMenu.addItem(.separator())
        applicationMenu.addItem(withTitle: strings.text("action.quit"), action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        applicationItem.submenu = applicationMenu
        main.addItem(applicationItem)

        let fileItem = NSMenuItem(title: strings.text("menu.file"), action: nil, keyEquivalent: "")
        let fileMenu = NSMenu(title: strings.text("menu.file"))
        fileMenu.addItem(withTitle: strings.text("menu.close"), action: #selector(NSWindow.performClose(_:)), keyEquivalent: "w")
        fileItem.submenu = fileMenu
        main.addItem(fileItem)

        let editItem = NSMenuItem(title: strings.text("menu.edit"), action: nil, keyEquivalent: "")
        let editMenu = NSMenu(title: strings.text("menu.edit"))
        editMenu.addItem(withTitle: strings.text("menu.undo"), action: Selector(("undo:")), keyEquivalent: "z")
        let redoItem = editMenu.addItem(withTitle: strings.text("menu.redo"), action: Selector(("redo:")), keyEquivalent: "z")
        redoItem.keyEquivalentModifierMask = [.command, .shift]
        editMenu.addItem(.separator())
        editMenu.addItem(withTitle: strings.text("menu.cut"), action: #selector(NSText.cut(_:)), keyEquivalent: "x")
        editMenu.addItem(withTitle: strings.text("menu.copy"), action: #selector(NSText.copy(_:)), keyEquivalent: "c")
        editMenu.addItem(withTitle: strings.text("menu.paste"), action: #selector(NSText.paste(_:)), keyEquivalent: "v")
        editMenu.addItem(withTitle: strings.text("menu.selectAll"), action: #selector(NSText.selectAll(_:)), keyEquivalent: "a")
        editItem.submenu = editMenu
        main.addItem(editItem)

        let windowItem = NSMenuItem(title: strings.text("menu.window"), action: nil, keyEquivalent: "")
        let windowMenu = NSMenu(title: strings.text("menu.window"))
        windowMenu.addItem(withTitle: strings.text("menu.minimize"), action: #selector(NSWindow.performMiniaturize(_:)), keyEquivalent: "m")
        windowMenu.addItem(withTitle: strings.text("menu.zoom"), action: #selector(NSWindow.performZoom(_:)), keyEquivalent: "")
        windowItem.submenu = windowMenu
        main.addItem(windowItem)
        NSApp.windowsMenu = windowMenu
        NSApp.mainMenu = main
    }
}
