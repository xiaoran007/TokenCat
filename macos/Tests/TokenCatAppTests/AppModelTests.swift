import AppKit
import XCTest
@testable import TokenCat
@testable import TokenCatKit

@MainActor
final class AppModelTests: XCTestCase {
    func testMenuStylePersistsWithoutInvalidatingUsageSettings() throws {
        let suite = "TokenCat.MenuStyleTests.\(UUID().uuidString)"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        let settings = AppSettings(defaults: defaults)
        XCTAssertEqual(settings.menuStyle, .system)
        var changes = 0
        let observer = settings.snapshotSettingsDidChange.sink { changes += 1 }
        defer { observer.cancel() }

        settings.menuStyle = .cards

        XCTAssertEqual(AppSettings(defaults: defaults).menuStyle, .cards)
        XCTAssertEqual(changes, 0, "A visual preset must not reopen the collector or invalidate usage.")
        settings.menuStyle = .system
        XCTAssertEqual(AppSettings(defaults: defaults).menuStyle, .system)
    }

    func testOpeningHistoricalTaskPreservesItsWindowAndLoadedSnapshot() async throws {
        _ = NSApplication.shared
        let suite = "TokenCat.AppModelTests.\(UUID().uuidString)"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        let settings = AppSettings(defaults: defaults)
        settings.home = NSTemporaryDirectory()
        let snapshot = MenuFixtures.dashboard()
        let model = AppModel(settings: settings, worker: FixtureUsageLoader(result: .success(snapshot)))
        model.window = .month
        await model.refresh()
        XCTAssertNotNil(model.dashboard)

        model.openTask("fixture-claude", window: .month)

        XCTAssertEqual(model.window, .month)
        XCTAssertEqual(model.selectedTaskId, "fixture-claude")
        XCTAssertEqual(model.selectedTask?.id, "fixture-claude")
        XCTAssertEqual(model.dashboard?.summary.eventCount, snapshot.summary.eventCount)
    }
}
