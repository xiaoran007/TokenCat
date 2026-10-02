import AppKit
import Combine
import ServiceManagement
import SwiftUI
import TokenCatKit

@MainActor
final class AppSettings: ObservableObject {
    private let defaults: UserDefaults
    @Published var language: AppLanguage { didSet { defaults.set(language.rawValue, forKey: "language") } }
    @Published var appearance: String { didSet { defaults.set(appearance, forKey: "appearance") } }
    @Published var showMenuCost: Bool { didSet { defaults.set(showMenuCost, forKey: "showMenuCost") } }
    @Published var showPaths: Bool { didSet { defaults.set(showPaths, forKey: "showPaths") } }
    @Published var home: String { didSet { defaults.set(home, forKey: "home") } }
    @Published var codexRoot: String { didSet { defaults.set(codexRoot, forKey: "codexRoot") } }
    @Published var claudeRoots: String { didSet { defaults.set(claudeRoots, forKey: "claudeRoots") } }
    @Published var pricingPath: String { didSet { defaults.set(pricingPath, forKey: "pricingPath") } }
    @Published var refreshSeconds: Int { didSet { defaults.set(refreshSeconds, forKey: "refreshSeconds") } }
    @Published var timezone: String { didSet { defaults.set(timezone, forKey: "timezone") } }
    @Published var loginError: String?
    @Published var loginEnabled = SMAppService.mainApp.status == .enabled

    init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
        defaults.register(defaults: ["language": "system", "appearance": "system", "showMenuCost": true,
                                     "showPaths": false, "home": NSHomeDirectory(), "codexRoot": "", "claudeRoots": "", "pricingPath": "",
                                     "refreshSeconds": 2, "timezone": ""])
        language = AppLanguage(rawValue: defaults.string(forKey: "language")!) ?? .system
        appearance = defaults.string(forKey: "appearance")!
        showMenuCost = defaults.bool(forKey: "showMenuCost")
        showPaths = defaults.bool(forKey: "showPaths")
        home = defaults.string(forKey: "home")!
        codexRoot = defaults.string(forKey: "codexRoot")!
        claudeRoots = defaults.string(forKey: "claudeRoots")!
        pricingPath = defaults.string(forKey: "pricingPath")!
        refreshSeconds = defaults.integer(forKey: "refreshSeconds")
        timezone = defaults.string(forKey: "timezone")!
    }
    var strings: Localizer { Localizer(language) }
    var colorScheme: ColorScheme? { appearance == "light" ? .light : (appearance == "dark" ? .dark : nil) }
    var timeZone: TimeZone? { timezone.isEmpty ? .autoupdatingCurrent : TimeZone(identifier: timezone) }
    var databaseURL: URL {
        FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("TokenCat", isDirectory: true).appendingPathComponent("usage.sqlite3")
    }
    var coreConfiguration: CoreConfiguration {
        CoreConfiguration(home: (home as NSString).expandingTildeInPath, databasePath: databaseURL.path,
                          codexRoot: codexRoot.isEmpty ? nil : (codexRoot as NSString).expandingTildeInPath,
                          claudeRoots: claudeRoots.split(whereSeparator: \.isNewline).map { (String($0).trimmingCharacters(in: .whitespaces) as NSString).expandingTildeInPath }.filter { !$0.isEmpty },
                          pricingPath: pricingPath.isEmpty ? nil : pricingPath)
    }
    var validHome: Bool {
        var isDirectory: ObjCBool = false
        return FileManager.default.fileExists(atPath: (home as NSString).expandingTildeInPath, isDirectory: &isDirectory) && isDirectory.boolValue
    }
    func setLogin(_ enabled: Bool) {
        do {
            if enabled { try SMAppService.mainApp.register() } else { try SMAppService.mainApp.unregister() }
            loginEnabled = SMAppService.mainApp.status == .enabled
            loginError = nil
        } catch { loginError = error.localizedDescription }
    }
}

@MainActor
final class AppModel: ObservableObject {
    let settings: AppSettings
    @Published private(set) var today: Dashboard?
    @Published private(set) var dashboard: Dashboard?
    @Published private(set) var refreshing = false
    @Published private(set) var error: String?
    @Published var window: TimeWindow = .today { didSet { requestRefresh() } }
    @Published var selectedTaskId: String?
    private let worker = CoreWorker()
    private var pollTask: Task<Void, Never>?
    private var cancellables = Set<AnyCancellable>()
    private var observers: [NSObjectProtocol] = []
    private var refreshPending = false

    init(settings: AppSettings) {
        self.settings = settings
        settings.objectWillChange.debounce(for: .milliseconds(400), scheduler: RunLoop.main).sink { [weak self] _ in self?.requestRefresh() }.store(in: &cancellables)
        observers.append(NSWorkspace.shared.notificationCenter.addObserver(forName: NSWorkspace.didWakeNotification, object: nil, queue: .main) { [weak self] _ in
            Task { @MainActor in self?.requestRefresh() }
        })
        observers.append(NotificationCenter.default.addObserver(forName: .NSSystemTimeZoneDidChange, object: nil, queue: .main) { [weak self] _ in
            Task { @MainActor in self?.requestRefresh() }
        })
    }

    func start() {
        guard pollTask == nil else { return }
        pollTask = Task { [weak self] in
            while !Task.isCancelled {
                guard let self else { return }
                await self.refresh()
                let delay = UInt64(max(2, self.settings.refreshSeconds)) * 1_000_000_000
                do { try await Task.sleep(nanoseconds: delay) } catch { return }
            }
        }
    }
    func requestRefresh() {
        if refreshing { refreshPending = true; return }
        Task { await refresh() }
    }
    private func query(for window: TimeWindow, now: Date, timezone: TimeZone) -> CoreQuery {
        let interval = window.interval(now: now, timeZone: timezone)
        return CoreQuery(sinceMs: interval.start.milliseconds, untilMs: interval.end.milliseconds,
                         timezone: timezone.identifier, showPaths: settings.showPaths)
    }
    func refresh() async {
        guard !refreshing else { return }
        let strings = settings.strings
        guard let timezone = settings.timeZone else { error = strings.text("settings.invalidTimezone"); return }
        guard settings.validHome else { error = strings.text("settings.invalidHome"); return }
        refreshing = true
        let now = Date()
        let requestedWindow = window
        let config = settings.coreConfiguration
        do {
            let values = try await worker.refresh(configuration: config, queries: [query(for: .today, now: now, timezone: timezone), query(for: requestedWindow, now: now, timezone: timezone)])
            today = values[0]
            if requestedWindow == window { dashboard = values[1] }
            error = nil
        } catch { self.error = error.localizedDescription }
        refreshing = false
        if refreshPending { refreshPending = false; requestRefresh() }
    }
    var selectedTask: BreakdownRow? { dashboard?.sessions.first { $0.id == selectedTaskId } }
    func openTask(_ id: String) { selectedTaskId = id; window = .today }
    deinit {
        pollTask?.cancel()
        for observer in observers {
            NSWorkspace.shared.notificationCenter.removeObserver(observer)
            NotificationCenter.default.removeObserver(observer)
        }
    }
}
