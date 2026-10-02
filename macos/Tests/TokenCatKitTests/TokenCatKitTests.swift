import XCTest
@testable import TokenCatKit

final class TokenCatKitTests: XCTestCase {
    private func fixture(schemaVersion: Int = 1) throws -> Data {
        let cost: [String: Any] = ["min_usd": 0.35, "max_usd": 0.45, "input_usd": 0.1, "cache_read_usd": 0.02,
            "cache_write_min_usd": 0.03, "cache_write_max_usd": 0.13, "output_usd": 0.2,
            "priced_tokens": 500, "total_tokens": 1000, "unpriced_events": 1, "uncertain_events": 1,
            "unknown_models": ["unpriced-test-model"]]
        let summary: [String: Any] = ["cost": cost, "input_tokens": 100, "cache_read_tokens": 300,
            "cache_write_tokens": 100, "output_tokens": 500, "reasoning_tokens": 200,
            "event_count": 2, "incomplete_events": 1, "latest_event_ms": 1_000]
        let parent: [String: Any] = ["id": "parent", "label": "session:parent", "provider": "claude", "parent_id": NSNull(), "summary": summary]
        let child: [String: Any] = ["id": "child", "label": "session:child", "provider": "claude", "parent_id": "parent", "summary": summary]
        let data: [String: Any] = ["schema_version": schemaVersion, "summary": summary, "providers": [], "models": [],
            "projects": [], "sessions": [child, parent], "timeline": [["timestamp_ms": 0, "summary": summary]],
            "states": [["provider": "codex", "session_id": "parent", "timestamp_ms": 1000, "kind": "quota", "data": ["percent": 40.0]]],
            "catalog_id": "fixture-v1", "catalog_retrieved_at": "2026-10-02", "catalog_sources": [],
            "last_scan": ["files_discovered": 2, "files_changed": 1, "events_upserted": 1, "checked_at_ms": 2000, "warnings": []]]
        return try JSONSerialization.data(withJSONObject: data)
    }
    func testNativeDashboardDecodingPreservesRangesAndTokenSubsets() throws {
        let snapshot = try Dashboard.decode(fixture())
        XCTAssertEqual(snapshot.summary.cost.minUsd, 0.35)
        XCTAssertTrue(snapshot.summary.cost.hasRange)
        XCTAssertEqual(snapshot.summary.cost.coverage, 0.5)
        XCTAssertNil(snapshot.summary.cacheReadRatio)
        XCTAssertEqual(snapshot.summary.reasoningTokens, 200)
        XCTAssertEqual(snapshot.rootSessions.map(\.id), ["parent"])
        XCTAssertEqual(snapshot.children(of: "parent").map(\.id), ["child"])
        let family = snapshot.familySummary(snapshot.rootSessions[0])
        XCTAssertEqual(family.minUsd, 0.7, accuracy: 0.000001)
        XCTAssertEqual(family.maxUsd, 0.9, accuracy: 0.000001)
        XCTAssertEqual(family.unpricedEvents, 2)
        XCTAssertEqual(family.uncertainEvents, 2)
        XCTAssertEqual(family.pricedTokens, 1000)
        XCTAssertEqual(family.totalTokens, 2000)
        XCTAssertEqual(family.unknownModels, ["unpriced-test-model"])
        XCTAssertEqual(snapshot.timeline[0].date, Date(timeIntervalSince1970: 0))
        XCTAssertEqual(snapshot.lastScan?.checkedAtMs, 2000)
    }
    func testUnsupportedSchemaIsRejected() throws {
        XCTAssertThrowsError(try Dashboard.decode(fixture(schemaVersion: 2)))
    }
    func testCacheRatioDoesNotOverflowLargeCounters() throws {
        var summary = try Dashboard.decode(fixture()).summary
        summary.inputTokens = UInt64.max
        summary.cacheReadTokens = UInt64.max
        summary.cacheWriteTokens = 0
        summary.incompleteEvents = 0
        XCTAssertEqual(summary.cacheReadRatio, 0.5)
    }
    func testUnknownPartialAndVerySmallCostsNeverLookFree() throws {
        let english = Localizer(.english)
        let chinese = Localizer(.simplifiedChinese)
        var cost = try Dashboard.decode(fixture()).summary.cost
        cost.minUsd = 0; cost.maxUsd = 0; cost.pricedTokens = 0
        XCTAssertEqual(english.cost(cost, compact: true), "Unpriced")
        XCTAssertEqual(chinese.cost(cost, compact: true), "尚未定价")
        cost.minUsd = 0.0025; cost.maxUsd = 0.0025; cost.pricedTokens = 100
        XCTAssertEqual(english.cost(cost, compact: true), "Known $0.0025")
        cost.unpricedEvents = 0
        XCTAssertEqual(english.cost(cost, compact: true), "$0.0025")
        XCTAssertEqual(english.money(0.000001, compact: true), "<$0.0001")
        cost.minUsd = 0; cost.maxUsd = 0.00000005
        XCTAssertEqual(english.cost(cost, compact: true), "$0.00–<$0.0001")
        XCTAssertTrue(chinese.money(0.000001, compact: true).hasPrefix("小于"))
        XCTAssertEqual(english.categoryCost(tokens: 100, min: 0, max: 0, hasUnpriced: true), "Unpriced")
        XCTAssertEqual(english.categoryCost(tokens: 100, min: 0.1, max: 0.1, hasUnpriced: true), "Known $0.10")
        XCTAssertEqual(english.categoryCost(tokens: 0, min: 0, max: 0, hasUnpriced: true), "$0.00")
    }
    func testCycleComponentsRemainReachableExactlyOnce() throws {
        var snapshot = try Dashboard.decode(fixture())
        let template = snapshot.sessions[0]
        func row(_ id: String, parent: String?) -> BreakdownRow {
            var value = template
            value.id = id; value.parentId = parent; value.label = "session:" + id
            return value
        }
        snapshot.sessions = [row("z", parent: "a"), row("a", parent: "z"), row("0-child", parent: "z"),
                             row("self", parent: "self"), row("normal", parent: nil)]
        XCTAssertEqual(snapshot.rootSessions.map(\.id), ["a", "normal", "self"])
        let reachable = snapshot.rootSessions.flatMap { snapshot.taskFamily($0).map(\.id) }
        XCTAssertEqual(reachable.count, 5)
        XCTAssertEqual(Set(reachable), Set(snapshot.sessions.map(\.id)))
        XCTAssertEqual(snapshot.familySummary(snapshot.rootSessions[0]).unpricedEvents, 3)
        XCTAssertEqual(snapshot.taskFamily(snapshot.rootSessions[2]).count, 1)
    }
    func testPrivacyDiagnosticsAndUnknownLabelsRespectPresentationContext() throws {
        let s = Localizer(.english)
        let warning = "Unable to read /Users/private-person/private-project/session.jsonl"
        let hidden = s.collectionDiagnostics([warning], showPaths: false)
        XCTAssertEqual(hidden[0], "1 collection warning")
        XCTAssertFalse(hidden.joined().contains("private-person"))
        XCTAssertFalse(hidden.joined().contains("session.jsonl"))
        XCTAssertEqual(s.collectionDiagnostics([warning], showPaths: true), [warning])
        XCTAssertEqual(s.collectionDiagnostics([], showPaths: false), [])
        var row = try Dashboard.decode(fixture()).sessions[0]
        row.id = "unknown"; row.label = "unknown"; row.provider = nil
        XCTAssertEqual(s.label(row, kind: .model), "Unknown model")
        XCTAssertEqual(s.label(row, kind: .project), "Unknown project")
    }
    func testBridgeEncodesNativeConfigurationAndWindowContract() throws {
        let encoder = JSONEncoder()
        encoder.keyEncodingStrategy = .convertToSnakeCase
        let config = CoreConfiguration(home: "/fixtures/home", databasePath: "/fixtures/usage.sqlite3", codexRoot: "/fixtures/codex", claudeRoots: ["/fixtures/claude"], pricingPath: nil)
        let encoded = try JSONSerialization.jsonObject(with: encoder.encode(config)) as! [String: Any]
        XCTAssertEqual(encoded["database_path"] as? String, "/fixtures/usage.sqlite3")
        XCTAssertEqual(encoded["codex_root"] as? String, "/fixtures/codex")
        XCTAssertEqual(encoded["claude_roots"] as? [String], ["/fixtures/claude"])
        let query = CoreQuery(sinceMs: 100, untilMs: 200, timezone: "America/New_York", showPaths: false)
        let queryJSON = try JSONSerialization.jsonObject(with: encoder.encode(query)) as! [String: Any]
        XCTAssertEqual(queryJSON["since_ms"] as? Int, 100)
        XCTAssertEqual(queryJSON["show_paths"] as? Bool, false)
        let payload = try JSONSerialization.jsonObject(with: fixture())
        let success = try CoreEnvelope<Dashboard>.decode(JSONSerialization.data(withJSONObject: ["ok": true, "data": payload]))
        XCTAssertTrue(success.ok)
        XCTAssertEqual(success.data?.catalogId, "fixture-v1")
        let failure = try CoreEnvelope<Dashboard>.decode(Data(#"{"ok":false,"error":"Malformed catalog"}"#.utf8))
        XCTAssertFalse(failure.ok)
        XCTAssertNil(failure.data)
        XCTAssertEqual(failure.error, "Malformed catalog")
    }
    func testResourceKeyParityAndNoUntranslatedKeys() {
        let english = Localizer.resourceKeys(.english)
        let chinese = Localizer.resourceKeys(.simplifiedChinese)
        XCTAssertEqual(english, chinese)
        XCTAssertGreaterThan(english.count, 90)
        for key in english {
            XCTAssertNotEqual(Localizer(.english).text(key), key)
            XCTAssertNotEqual(Localizer(.simplifiedChinese).text(key), key)
        }
        XCTAssertEqual(Localizer(.english).eventCount(1), "1 usage event")
        XCTAssertEqual(Localizer(.english).eventCount(2), "2 usage events")
        XCTAssertEqual(Localizer(.simplifiedChinese).eventCount(2), "2 条用量记录")
    }
    func testLocaleFormattingKeepsCurrencyExplicitAndDoesNotRoundSmallCostsAway() throws {
        XCTAssertEqual(Localizer(.english).money(0.0025), "$0.0025")
        XCTAssertTrue(Localizer(.simplifiedChinese).money(1.25).contains("1.25"))
        let snapshot = try Dashboard.decode(fixture())
        XCTAssertEqual(Localizer(.english).cost(snapshot.summary.cost, compact: true), "Known $0.35–$0.45")
        XCTAssertEqual(Localizer(.english).count(12345), "12,345")
    }
    func testWindowsUseLocalMidnightAcrossDaylightSaving() {
        let zone = TimeZone(identifier: "America/New_York")!
        let iso = ISO8601DateFormatter()
        let now = iso.date(from: "2026-03-09T03:59:00Z")!
        let today = TimeWindow.today.interval(now: now, timeZone: zone)
        XCTAssertEqual(today.start, iso.date(from: "2026-03-08T05:00:00Z"))
        let week = TimeWindow.week.interval(now: now, timeZone: zone)
        XCTAssertEqual(week.start, iso.date(from: "2026-03-02T05:00:00Z"))
        XCTAssertEqual(Date(milliseconds: 123456789).milliseconds, 123456789)
    }
}
