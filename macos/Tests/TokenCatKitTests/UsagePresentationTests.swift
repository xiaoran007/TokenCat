import XCTest
@testable import TokenCatKit

final class UsagePresentationTests: XCTestCase {
    private func row(_ id: String, label: String? = nil, provider: Harness? = .codex,
                     parent: String? = nil, cost: Double = 1, maxCost: Double? = nil,
                     tokens: UInt64 = 100, latest: Int64? = 1_000) -> BreakdownRow {
        let cost = CostSummary(minUsd: cost, maxUsd: maxCost ?? cost, inputUsd: cost,
                               cacheReadUsd: 0, cacheWriteMinUsd: 0, cacheWriteMaxUsd: 0,
                               outputUsd: 0, pricedTokens: tokens, totalTokens: tokens,
                               unpricedEvents: 0, uncertainEvents: 0, unknownModels: [])
        let summary = UsageSummary(cost: cost, inputTokens: tokens, cacheReadTokens: 0,
                                   cacheWriteTokens: 0, outputTokens: 0, reasoningTokens: 0,
                                   eventCount: 1, incompleteEvents: 0, latestEventMs: latest)
        return BreakdownRow(id: id, label: label ?? "session:\(id)", provider: provider,
                            parentId: parent, summary: summary)
    }

    private func dashboard(_ sessions: [BreakdownRow]) -> Dashboard {
        Dashboard(schemaVersion: 1, summary: row("summary").summary, providers: [], models: [],
                  projects: [], sessions: sessions, timeline: [], states: [], catalogId: "fixture",
                  catalogRetrievedAt: "2026-10-02", catalogSources: [], lastScan: nil)
    }

    func testSortOptionsExposeStableIdentitiesAndLocalizationKeys() {
        XCTAssertEqual(UsageSort.allCases.map(\.rawValue), ["cost", "tokens", "recent"])
        XCTAssertEqual(UsageSort.allCases.map(\.id), UsageSort.allCases)
        XCTAssertEqual(UsageSort.allCases.map(\.localizationKey), ["sort.cost", "sort.tokens", "sort.recent"])
    }

    func testRowSearchTrimsWhitespaceAndMatchesDisplayedNamesOrProvider() {
        let localizer = Localizer(.english)
        let rows = [row("a", label: "gpt-codex", provider: .codex),
                    row("b", label: "Sonnet", provider: .claude)]
        XCTAssertEqual(localizer.matchingRows(rows, query: " \nSONNET\t", kind: .model, sort: .cost).map(\.id), ["b"])
        XCTAssertEqual(localizer.matchingRows(rows, query: " cLaUdE ", kind: .model, sort: .cost).map(\.id), ["b"])
        XCTAssertEqual(localizer.matchingRows(rows, query: "  \n", kind: .model, sort: .cost).map(\.id), ["a", "b"])
        XCTAssertTrue(localizer.matchingRows(rows, query: "missing", kind: .model, sort: .cost).isEmpty)
    }

    func testSearchUsesLocalizedDisplayLabelsWithoutSearchingHiddenIdentifiers() {
        let rows = [row("/Users/private/project", label: "project:abc123", provider: nil),
                    row("unknown", label: "unknown", provider: nil)]
        let chinese = Localizer(.simplifiedChinese)
        XCTAssertEqual(chinese.matchingRows(rows, query: "项目 abc123", kind: .project, sort: .cost).map(\.id), ["/Users/private/project"])
        XCTAssertEqual(chinese.matchingRows(rows, query: "未知项目", kind: .project, sort: .cost).map(\.id), ["unknown"])
        XCTAssertTrue(chinese.matchingRows(rows, query: "private", kind: .project, sort: .cost).isEmpty)
        XCTAssertTrue(chinese.matchingRows(rows, query: "project:", kind: .project, sort: .cost).isEmpty)
        XCTAssertTrue(chinese.matchingRows(rows, query: "Project abc123", kind: .project, sort: .cost).isEmpty)
    }

    func testRowSortUsesCostUpperBoundTokensAndLatestEvent() {
        let rows = [row("a", cost: 4, tokens: 200, latest: nil),
                    row("b", cost: 1, maxCost: 8, tokens: 100, latest: 2_000),
                    row("c", cost: 2, tokens: 300, latest: 1_000)]
        let localizer = Localizer(.english)
        XCTAssertEqual(localizer.matchingRows(rows, query: "", kind: .model, sort: .cost).map(\.id), ["b", "a", "c"])
        XCTAssertEqual(localizer.matchingRows(rows, query: "", kind: .model, sort: .tokens).map(\.id), ["c", "a", "b"])
        XCTAssertEqual(localizer.matchingRows(rows, query: "", kind: .model, sort: .recent).map(\.id), ["b", "c", "a"])
    }

    func testEqualMetricsUseStableIdentifierOrderAndKeepLargeTokenCountsExact() {
        let localizer = Localizer(.english)
        let tied = [row("z"), row("a"), row("m")]
        for sort in UsageSort.allCases {
            XCTAssertEqual(localizer.matchingRows(tied, query: "", kind: .model, sort: sort).map(\.id), ["a", "m", "z"])
            XCTAssertEqual(dashboard(tied).sortedTasks(tied, by: sort).map(\.id), ["a", "m", "z"])
        }
        let large = [row("a", tokens: UInt64.max - 1), row("z", tokens: UInt64.max)]
        XCTAssertEqual(localizer.matchingRows(large, query: "", kind: .model, sort: .tokens).map(\.id), ["z", "a"])
    }

    func testTaskSearchFindsChildWithoutMatchingParentAndReturnsFlatResults() {
        let snapshot = dashboard([row("parent", label: "Root task"),
                                  row("child", label: "Searchable child", provider: .claude, parent: "parent"),
                                  row("other", label: "Unrelated")])
        XCTAssertEqual(snapshot.matchingTasks(query: " CHILD\n", localizer: Localizer(.english), sort: .cost).map(\.id), ["child"])
        XCTAssertEqual(snapshot.matchingTasks(query: "Claude", localizer: Localizer(.english), sort: .cost).map(\.id), ["child"])
        XCTAssertTrue(snapshot.matchingTasks(query: "missing", localizer: Localizer(.english), sort: .cost).isEmpty)
        XCTAssertEqual(Set(snapshot.matchingTasks(query: " \n", localizer: Localizer(.english), sort: .cost).map(\.id)), ["parent", "child", "other"])
    }

    func testTaskSortingAggregatesNestedFamilyCostTokensAndLatestEvent() {
        let snapshot = dashboard([row("parent", cost: 0, tokens: 0, latest: 100),
                                  row("child", parent: "parent", cost: 2, tokens: 200, latest: 200),
                                  row("grandchild", parent: "child", cost: 3, tokens: 300, latest: 3_000),
                                  row("other", cost: 4, tokens: 400, latest: 2_000)])
        for sort in UsageSort.allCases {
            XCTAssertEqual(snapshot.sortedTasks(snapshot.rootSessions, by: sort).map(\.id), ["parent", "other"])
        }
        XCTAssertEqual(snapshot.matchingTasks(query: "Task", localizer: Localizer(.english), sort: .cost).map(\.id), ["child", "parent", "other", "grandchild"])
    }

    func testTaskFamilySortingCountsCyclesOnceAndKeepsMissingDatesLast() {
        let snapshot = dashboard([row("a", parent: "b", cost: 2, tokens: 200, latest: nil),
                                  row("b", parent: "a", cost: 3, tokens: 300, latest: nil),
                                  row("other", cost: 6, tokens: 600, latest: 100)])
        for sort in UsageSort.allCases {
            XCTAssertEqual(snapshot.sortedTasks(snapshot.rootSessions, by: sort).map(\.id), ["other", "a"])
        }
    }
}
