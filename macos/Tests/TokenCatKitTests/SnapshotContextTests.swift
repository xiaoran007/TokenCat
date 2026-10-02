import XCTest
@testable import TokenCatKit

final class SnapshotContextTests: XCTestCase {
    private let configuration = CoreConfiguration(home: "/fixtures/home", databasePath: "/fixtures/usage.sqlite3",
                                                codexRoot: nil, claudeRoots: [], pricingPath: nil)

    func testQueriesShareCapturedTimeZonePrivacyAndEndTime() {
        let zone = TimeZone(identifier: "America/New_York")!
        let now = ISO8601DateFormatter().date(from: "2026-03-09T03:59:00Z")!
        let context = SnapshotContext(configuration: configuration, window: .week, timeZone: zone, showPaths: false)
        let queries = context.queries(now: now)

        XCTAssertEqual(queries.count, 2)
        XCTAssertEqual(queries[0].sinceMs, TimeWindow.today.interval(now: now, timeZone: zone).start.milliseconds)
        XCTAssertEqual(queries[1].sinceMs, TimeWindow.week.interval(now: now, timeZone: zone).start.milliseconds)
        XCTAssertEqual(queries.map(\.untilMs), [now.milliseconds, now.milliseconds])
        XCTAssertEqual(queries.map(\.timezone), [zone.identifier, zone.identifier])
        XCTAssertEqual(queries.map(\.showPaths), [false, false])
    }

    func testChangedWindowTimeZoneOrPrivacyRejectsThePreviousContext() {
        let zone = TimeZone(identifier: "America/New_York")!
        let previous = SnapshotContext(configuration: configuration, window: .today, timeZone: zone, showPaths: true)
        XCTAssertEqual(previous.queries(now: Date()).map(\.showPaths), [true, true])
        XCTAssertNotEqual(previous, SnapshotContext(configuration: configuration, window: .week, timeZone: zone, showPaths: true))
        XCTAssertNotEqual(previous, SnapshotContext(configuration: configuration, window: .today, timeZone: TimeZone(identifier: "Asia/Shanghai")!, showPaths: true))
        XCTAssertNotEqual(previous, SnapshotContext(configuration: configuration, window: .today, timeZone: zone, showPaths: false))
    }

    func testChangedSourceOrPricingRejectsThePreviousContext() {
        let zone = TimeZone(identifier: "America/New_York")!
        let previous = SnapshotContext(configuration: configuration, window: .today, timeZone: zone, showPaths: false)
        let changedConfigurations = [
            CoreConfiguration(home: "/different/home", databasePath: configuration.databasePath, codexRoot: nil, claudeRoots: [], pricingPath: nil),
            CoreConfiguration(home: configuration.home, databasePath: "/different/usage.sqlite3", codexRoot: nil, claudeRoots: [], pricingPath: nil),
            CoreConfiguration(home: configuration.home, databasePath: configuration.databasePath, codexRoot: "/different/codex", claudeRoots: [], pricingPath: nil),
            CoreConfiguration(home: configuration.home, databasePath: configuration.databasePath, codexRoot: nil, claudeRoots: ["/different/claude"], pricingPath: nil),
            CoreConfiguration(home: configuration.home, databasePath: configuration.databasePath, codexRoot: nil, claudeRoots: [], pricingPath: "/different/pricing.json")
        ]
        for changed in changedConfigurations {
            XCTAssertNotEqual(previous, SnapshotContext(configuration: changed, window: .today, timeZone: zone, showPaths: false))
        }
        XCTAssertEqual(previous, SnapshotContext(configuration: configuration, window: .today, timeZone: zone, showPaths: false))
    }
}
