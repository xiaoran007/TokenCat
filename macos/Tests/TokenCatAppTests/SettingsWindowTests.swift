import AppKit
import SwiftUI
import XCTest
@testable import TokenCat
@testable import TokenCatKit

@MainActor
final class SettingsWindowTests: XCTestCase {
    func testOpeningSettingsCreatesAVisibleWindowAndReusesIt() throws {
        try withController { controller, settings, model in
            XCTAssertNil(controller.window)

            controller.open()

            let window = try XCTUnwrap(controller.window)
            XCTAssertTrue(window.isVisible)
            XCTAssertTrue(window.canBecomeKey)
            XCTAssertFalse(window.isReleasedWhenClosed)
            XCTAssertEqual(window.title, settings.strings.text("settings.title"))
            let host = try XCTUnwrap(window.contentViewController as? NSHostingController<SettingsWindowContent>)
            XCTAssertTrue(host.rootView.settings === settings)
            XCTAssertTrue(host.rootView.model === model)
            host.view.layoutSubtreeIfNeeded()
            XCTAssertGreaterThanOrEqual(host.view.bounds.width, 590)
            XCTAssertGreaterThanOrEqual(host.view.bounds.height, 520)

            controller.open()

            XCTAssertTrue(controller.window === window)
            XCTAssertTrue(window.isVisible)
        }
    }

    func testClosedSettingsWindowReopensWithSharedState() throws {
        try withController { controller, settings, _ in
            controller.open()
            let window = try XCTUnwrap(controller.window)
            window.performClose(nil)
            XCTAssertFalse(window.isVisible)

            settings.language = .simplifiedChinese
            settings.appearance = "dark"
            controller.open()

            XCTAssertTrue(controller.window === window)
            XCTAssertTrue(window.isVisible)
            XCTAssertEqual(window.title, settings.strings.text("settings.title"))
            XCTAssertEqual(window.appearance?.name, .darkAqua)
        }
    }

    func testOpenWindowTracksLanguageAndAppearanceChanges() throws {
        try withController { controller, settings, _ in
            controller.open()
            let window = try XCTUnwrap(controller.window)

            settings.language = .simplifiedChinese
            settings.appearance = "dark"
            XCTAssertEqual(window.title, Localizer(.simplifiedChinese).text("settings.title"))
            XCTAssertEqual(window.appearance?.name, .darkAqua)

            settings.language = .english
            settings.appearance = "light"
            XCTAssertEqual(window.title, Localizer(.english).text("settings.title"))
            XCTAssertEqual(window.appearance?.name, .aqua)

            settings.appearance = "system"
            XCTAssertNil(window.appearance)
        }
    }

    private func withController(_ body: (SettingsWindowController, AppSettings, AppModel) throws -> Void) throws {
        _ = NSApplication.shared
        let suite = "TokenCat.SettingsWindowTests.\(UUID().uuidString)"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        let settings = AppSettings(defaults: defaults)
        settings.language = .english
        settings.appearance = "system"
        let model = AppModel(settings: settings, worker: FixtureUsageLoader(result: .success(MenuFixtures.dashboard())))
        let controller = SettingsWindowController(settings: settings, model: model)
        defer { controller.close() }
        try body(controller, settings, model)
    }
}
