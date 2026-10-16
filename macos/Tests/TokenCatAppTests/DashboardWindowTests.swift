import AppKit
import SwiftUI
import XCTest
@testable import TokenCat
@testable import TokenCatKit

@MainActor
final class DashboardWindowTests: XCTestCase {
    func testDashboardReusesItsWindowAndTracksAppearance() async throws {
        _ = NSApplication.shared
        let suite = "TokenCat.DashboardWindowTests.\(UUID().uuidString)"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        let settings = AppSettings(defaults: defaults)
        let model = AppModel(settings: settings, worker: FixtureUsageLoader(result: .success(MenuFixtures.dashboard())))
        let settingsWindow = SettingsWindowController(settings: settings, model: model)
        let controller = DashboardWindowController(settings: settings, model: model, settingsWindow: settingsWindow)
        defer { controller.close() }
        XCTAssertNil(controller.window)

        controller.open()
        let window = try XCTUnwrap(controller.window)
        XCTAssertTrue(window.isVisible)
        XCTAssertTrue(window.styleMask.contains(.resizable))
        XCTAssertTrue(window.styleMask.contains(.miniaturizable))
        XCTAssertFalse(window.isReleasedWhenClosed)
        XCTAssertEqual(window.contentMinSize, NSSize(width: 800, height: 560))
        let host = try XCTUnwrap(window.contentViewController as? NSHostingController<DashboardWindowContent>)
        XCTAssertTrue(host.rootView.settings === settings)
        XCTAssertTrue(host.rootView.model === model)
        XCTAssertTrue(host.rootView.settingsWindow === settingsWindow)
        host.view.layoutSubtreeIfNeeded()
        try await Task.sleep(for: .milliseconds(50))
        XCTAssertNotNil(window.toolbar, "The hosted dashboard must retain its SwiftUI toolbar.")

        window.performClose(nil)
        XCTAssertFalse(window.isVisible)
        settings.appearance = "dark"
        controller.open()
        XCTAssertTrue(controller.window === window)
        XCTAssertTrue(window.isVisible)
        XCTAssertEqual(window.appearance?.name, .darkAqua)
        settings.appearance = "light"
        XCTAssertEqual(window.appearance?.name, .aqua)
        settings.appearance = "system"
        XCTAssertNil(window.appearance)
    }
}
