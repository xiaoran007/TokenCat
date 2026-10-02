import AppKit
import XCTest
@testable import TokenCat
@testable import TokenCatKit

@MainActor
final class AppModelTests: XCTestCase {
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
