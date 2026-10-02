import Foundation

public enum UsageSort: String, CaseIterable, Identifiable, Sendable {
    case cost, tokens, recent
    public var id: Self { self }
    public var localizationKey: String { "sort.\(rawValue)" }
}

public extension Localizer {
    func matchingRows(_ rows: [BreakdownRow], query: String, kind: BreakdownKind, sort: UsageSort) -> [BreakdownRow] {
        let search = query.trimmingCharacters(in: .whitespacesAndNewlines)
        return sortedUsageRows(rows.filter { matches($0, search: search, kind: kind) }.map {
            RankedUsage(row: $0, cost: $0.summary.cost, latestEventMs: $0.summary.latestEventMs)
        }, by: sort)
    }

    fileprivate func matches(_ row: BreakdownRow, search: String, kind: BreakdownKind) -> Bool {
        search.isEmpty || label(row, kind: kind).localizedCaseInsensitiveContains(search)
            || row.provider?.label.localizedCaseInsensitiveContains(search) == true
    }
}

public extension Dashboard {
    /// Searches every task, including children of collapsed or unmatched parents.
    func matchingTasks(query: String, localizer: Localizer, sort: UsageSort) -> [BreakdownRow] {
        let search = query.trimmingCharacters(in: .whitespacesAndNewlines)
        return sortedTasks(sessions.filter { localizer.matches($0, search: search, kind: .session) }, by: sort)
    }

    /// Task rows represent the whole family, so ordering uses the same totals.
    func sortedTasks(_ rows: [BreakdownRow], by sort: UsageSort) -> [BreakdownRow] {
        sortedUsageRows(rows.map {
            RankedUsage(row: $0, cost: familySummary($0),
                        latestEventMs: taskFamily($0).compactMap(\.summary.latestEventMs).max())
        }, by: sort)
    }
}

private struct RankedUsage {
    let row: BreakdownRow
    let cost: CostSummary
    let latestEventMs: Int64?
}

private func sortedUsageRows(_ rows: [RankedUsage], by sort: UsageSort) -> [BreakdownRow] {
    rows.sorted { lhs, rhs in
        switch sort {
        case .cost:
            if lhs.cost.maxUsd != rhs.cost.maxUsd { return lhs.cost.maxUsd > rhs.cost.maxUsd }
        case .tokens:
            if lhs.cost.totalTokens != rhs.cost.totalTokens { return lhs.cost.totalTokens > rhs.cost.totalTokens }
        case .recent:
            let left = lhs.latestEventMs ?? .min
            let right = rhs.latestEventMs ?? .min
            if left != right { return left > right }
        }
        return lhs.row.id < rhs.row.id
    }.map(\.row)
}
