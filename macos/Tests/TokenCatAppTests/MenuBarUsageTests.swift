import AppKit
import XCTest
@testable import TokenCat
@testable import TokenCatKit

@MainActor
final class MenuBarUsageTests: XCTestCase {
    func testUsageRequiresOptInAndPersistsTheSwitchAndMetric() throws {
        let suite = "TokenCat.MenuBarUsageSettings.\(UUID().uuidString)"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        // The old cost preference must not silently opt users into the new display.
        defaults.set(true, forKey: "showMenuCost")
        let settings = AppSettings(defaults: defaults)
        XCTAssertFalse(settings.showMenuUsage)
        XCTAssertEqual(settings.menuBarMetric, .cost)

        settings.showMenuUsage = true
        settings.menuBarMetric = .tokens
        let reopened = AppSettings(defaults: defaults)
        XCTAssertTrue(reopened.showMenuUsage)
        XCTAssertEqual(reopened.menuBarMetric, .tokens)

        reopened.showMenuUsage = false
        let disabled = AppSettings(defaults: defaults)
        XCTAssertFalse(disabled.showMenuUsage)
        XCTAssertEqual(disabled.menuBarMetric, .tokens, "Turning the display off must retain the selected content.")
    }

    func testMenuBarUpdatesImmediatelyForSwitchMetricAndLoadedUsage() async throws {
        _ = NSApplication.shared
        let suite = "TokenCat.MenuBarUsageController.\(UUID().uuidString)"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        let settings = AppSettings(defaults: defaults)
        settings.language = .english
        let snapshot = MenuFixtures.dashboard()
        let model = AppModel(settings: settings, worker: FixtureUsageLoader(result: .success(snapshot)))
        let controller = MenuBarController(settings: settings, model: model,
            settingsWindow: SettingsWindowController(settings: settings, model: model), openDashboard: {})
        controller.start()
        defer { controller.stop() }
        let button = try XCTUnwrap(controller.statusItem?.button)
        XCTAssertNotNil(button.image)
        XCTAssertEqual(button.title, "")
        settings.showMenuUsage = true
        XCTAssertEqual(button.title, "", "No statistic should be invented before today's usage is loaded.")

        await model.refresh()
        XCTAssertNotNil(model.today)
        XCTAssertEqual(button.title, " " + settings.strings.cost(snapshot.summary.cost, compact: true))
        settings.menuBarMetric = .tokens
        XCTAssertEqual(button.title, " " + settings.strings.compactCount(snapshot.summary.cost.totalTokens) + " tokens")
        settings.language = .simplifiedChinese
        XCTAssertEqual(button.title, " " + settings.strings.compactCount(snapshot.summary.cost.totalTokens) + " tokens")

        settings.showMenuUsage = false
        XCTAssertEqual(button.title, "")
        settings.menuBarMetric = .cost
        await model.refresh()
        XCTAssertEqual(button.title, "")
        settings.showMenuUsage = true
        XCTAssertEqual(button.title, " " + settings.strings.cost(snapshot.summary.cost, compact: true))
    }
}
