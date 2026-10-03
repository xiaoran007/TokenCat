import Foundation
@testable import TokenCat
@testable import TokenCatKit

struct FixtureUsageLoader: UsageLoading {
    let result: Result<Dashboard, CoreFailure>

    func refresh(configuration: CoreConfiguration, queries: [CoreQuery]) async throws -> [Dashboard] {
        let snapshot = try result.get()
        return queries.map { _ in snapshot }
    }
}

enum MenuFixtures {
    static func dashboard(empty: Bool = false) -> Dashboard {
        let checkedAt = Date().milliseconds
        func summary(_ units: Int) -> UsageSummary {
            let tokens = UInt64(units) * 100_000
            return UsageSummary(
                cost: CostSummary(minUsd: Double(units) * 0.15, maxUsd: Double(units) * 0.17,
                                  inputUsd: Double(units) * 0.03, cacheReadUsd: Double(units) * 0.01,
                                  cacheWriteMinUsd: Double(units) * 0.01, cacheWriteMaxUsd: Double(units) * 0.03,
                                  outputUsd: Double(units) * 0.1, pricedTokens: tokens, totalTokens: tokens,
                                  unpricedEvents: 0, uncertainEvents: units, unknownModels: []),
                inputTokens: tokens / 5, cacheReadTokens: tokens * 3 / 5, cacheWriteTokens: tokens / 20,
                outputTokens: tokens * 3 / 20, reasoningTokens: tokens / 20,
                eventCount: units, incompleteEvents: 0, latestEventMs: units == 0 ? nil : checkedAt - 120_000)
        }
        func row(_ id: String, _ label: String, _ provider: Harness, units: Int, parent: String? = nil) -> BreakdownRow {
            BreakdownRow(id: id, label: label, provider: provider, parentId: parent, summary: summary(units))
        }
        let hour: Int64 = 3_600_000
        let start = checkedAt / hour * hour - 7 * hour
        return Dashboard(
            schemaVersion: 1, summary: summary(empty ? 0 : 80),
            providers: empty ? [] : [row("codex", "Codex", .codex, units: 50), row("claude", "Claude", .claude, units: 30)],
            models: empty ? [] : [row("gpt-5.4", "gpt-5.4", .codex, units: 50), row("claude-sonnet-4-6", "claude-sonnet-4-6", .claude, units: 30)],
            projects: empty ? [] : [row("project:fixture", "TokenCat", .codex, units: 80)],
            sessions: empty ? [] : [row("fixture-codex", "session:fixture-codex", .codex, units: 50),
                                    row("fixture-claude", "session:fixture-claude", .claude, units: 20),
                                    row("fixture-child", "session:fixture-child", .claude, units: 10, parent: "fixture-claude")],
            timeline: [3, 7, 9, 11, 6, 18, 16, 10].enumerated().map {
                TimelineBucket(timestampMs: start + Int64($0.offset) * hour, summary: summary(empty ? 0 : $0.element))
            },
            states: [], catalogId: "layout-test-fixture", catalogRetrievedAt: "2026-10-02", catalogSources: [],
            lastScan: ScanReport(filesDiscovered: empty ? 0 : 3, filesChanged: 0, eventsUpserted: 0,
                                 checkedAtMs: checkedAt, warnings: []))
    }
}
