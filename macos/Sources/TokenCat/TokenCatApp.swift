import AppKit
import SwiftUI
import TokenCatKit

@main
struct TokenCatApp: App {
    @StateObject private var settings: AppSettings
    @StateObject private var model: AppModel

    init() {
        let settings = AppSettings()
        _settings = StateObject(wrappedValue: settings)
        _model = StateObject(wrappedValue: AppModel(settings: settings))
    }
    var body: some Scene {
        MenuBarExtra {
            MenuPanel()
                .environmentObject(model).environmentObject(settings)
                .environment(\.locale, settings.language.locale)
                .tint(TokenCatTheme.accent)
                .preferredColorScheme(settings.colorScheme)
                .task { model.start() }
        } label: {
            Label {
                if settings.showMenuCost, let today = model.today {
                    Text(settings.strings.cost(today.summary.cost, compact: true)).monospacedDigit()
                } else { Text(settings.strings.text("app.name")) }
            } icon: { Image(systemName: "cat.fill") }
                .accessibilityLabel(settings.strings.text("accessibility.menu"))
        }
        .menuBarExtraStyle(.window)

        Window(settings.strings.text("app.name"), id: "dashboard") {
            DashboardView()
                .environmentObject(model).environmentObject(settings)
                .environment(\.locale, settings.language.locale)
                .transformEnvironment(\.timeZone) { timeZone in
                    if let configuredTimeZone = settings.timeZone { timeZone = configuredTimeZone }
                }
                .tint(TokenCatTheme.accent)
                .preferredColorScheme(settings.colorScheme)
                .task { model.start() }
        }
        .defaultSize(width: 1040, height: 720)
        .windowStyle(.automatic)
        .commands { CommandGroup(replacing: .newItem) {} }

        Settings {
            SettingsView()
                .environmentObject(model).environmentObject(settings)
                .environment(\.locale, settings.language.locale)
                .tint(TokenCatTheme.accent)
                .preferredColorScheme(settings.colorScheme)
        }
    }
}
