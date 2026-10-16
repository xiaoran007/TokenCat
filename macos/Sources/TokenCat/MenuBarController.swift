import AppKit
import Combine
import TokenCatKit

@MainActor
final class MenuBarController: NSObject {
    private let settings: AppSettings
    private let model: AppModel
    private let menu: MenuPanelController
    private(set) var statusItem: NSStatusItem?
    private var subscriptions = Set<AnyCancellable>()
    private var workspaceObserver: NSObjectProtocol?

    init(settings: AppSettings, model: AppModel, settingsWindow: SettingsWindowController,
         openDashboard: @escaping () -> Void) {
        self.settings = settings
        self.model = model
        menu = MenuPanelController(settings: settings, model: model, settingsWindow: settingsWindow,
                                   openDashboard: openDashboard)
        super.init()
        settings.$language.combineLatest(settings.$showMenuUsage, settings.$menuBarMetric, model.$today)
            .sink { [weak self] language, showUsage, metric, today in
                self?.updateLabel(language: language, showUsage: showUsage, metric: metric, today: today)
            }.store(in: &subscriptions)
        settings.$appearance.sink { [weak self] in self?.menu.updateAppearance($0) }.store(in: &subscriptions)
        settings.$menuStyle.dropFirst().sink { [weak self] _ in
            // @Published fires before the new preset reaches the hosted SwiftUI tree.
            DispatchQueue.main.async { [weak self] in self?.menu.resizeToFit() }
        }.store(in: &subscriptions)
    }

    func start() {
        guard statusItem == nil else { return }
        let item = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        statusItem = item
        if let button = item.button {
            button.image = TokenCatBrand.menuMark
            button.imagePosition = .imageLeading
            button.target = self
            button.action = #selector(toggleMenu)
            button.sendAction(on: [.leftMouseUp, .rightMouseUp])
        }
        updateLabel(language: settings.language, showUsage: settings.showMenuUsage, metric: settings.menuBarMetric, today: model.today)
        workspaceObserver = NSWorkspace.shared.notificationCenter.addObserver(
            forName: NSWorkspace.activeSpaceDidChangeNotification, object: nil, queue: .main) { [weak self] _ in
                Task { @MainActor in self?.menu.hide() }
            }
    }

    func stop() {
        menu.hide()
        if let statusItem { NSStatusBar.system.removeStatusItem(statusItem) }
        statusItem = nil
        if let workspaceObserver { NSWorkspace.shared.notificationCenter.removeObserver(workspaceObserver) }
        workspaceObserver = nil
    }

    @objc private func toggleMenu() {
        guard let button = statusItem?.button else { return }
        if menu.panel.isVisible { menu.hide() }
        else { menu.show(relativeTo: button) }
    }

    private func updateLabel(language: AppLanguage, showUsage: Bool, metric: MenuBarMetric, today: Dashboard?) {
        guard let button = statusItem?.button else { return }
        let strings = Localizer(language)
        if showUsage, let today {
            switch metric {
            case .cost: button.title = " " + strings.cost(today.summary.cost, compact: true)
            case .tokens: button.title = " " + strings.compactCount(today.summary.cost.totalTokens) + " tokens"
            }
        } else {
            button.title = ""
        }
        button.toolTip = strings.text("app.name")
        button.setAccessibilityLabel(strings.text("accessibility.menu"))
    }
}
