import Foundation

public enum Harness: String, Codable, Sendable {
    case codex, claude, opencode, antigravity
    public var label: String {
        switch self {
        case .codex: "Codex"
        case .claude: "Claude Code"
        case .opencode: "OpenCode"
        case .antigravity: "Antigravity"
        }
    }
    public var symbol: String {
        switch self {
        case .codex: "terminal"
        case .claude: "sparkle"
        case .opencode: "chevron.left.forwardslash.chevron.right"
        case .antigravity: "a.circle"
        }
    }
}

public struct PricingMatch: Codable, Hashable, Sendable {
    public var model: String
    public var pricedModel: String
    public var source: String
    public var kind: String
}

public struct CostSummary: Codable, Sendable {
    public var minUsd: Double
    public var maxUsd: Double
    public var inputUsd: Double
    public var cacheReadUsd: Double
    public var cacheWriteMinUsd: Double
    public var cacheWriteMaxUsd: Double
    public var outputUsd: Double
    public var pricedTokens: UInt64
    public var totalTokens: UInt64
    public var unpricedEvents: Int
    public var uncertainEvents: Int
    public var unknownModels: [String]
    public var pricingMatches: [PricingMatch]? = nil
    public var hasRange: Bool { maxUsd != minUsd }
    public var coverage: Double? { totalTokens == 0 ? nil : Double(pricedTokens) / Double(totalTokens) }
    public mutating func add(_ other: CostSummary) {
        minUsd += other.minUsd; maxUsd += other.maxUsd
        inputUsd += other.inputUsd; cacheReadUsd += other.cacheReadUsd
        cacheWriteMinUsd += other.cacheWriteMinUsd; cacheWriteMaxUsd += other.cacheWriteMaxUsd
        outputUsd += other.outputUsd
        // Native counters saturate at their representable maximum as well.
        let priced = pricedTokens.addingReportingOverflow(other.pricedTokens)
        pricedTokens = priced.overflow ? .max : priced.partialValue
        let total = totalTokens.addingReportingOverflow(other.totalTokens)
        totalTokens = total.overflow ? .max : total.partialValue
        unpricedEvents += other.unpricedEvents; uncertainEvents += other.uncertainEvents
        unknownModels = Array(Set(unknownModels + other.unknownModels)).sorted()
        pricingMatches = Array(Set((pricingMatches ?? []) + (other.pricingMatches ?? [])))
            .sorted { ($0.model, $0.source, $0.pricedModel) < ($1.model, $1.source, $1.pricedModel) }
    }
}

public enum BreakdownKind { case provider, model, project, session }

public struct UsageSummary: Codable, Sendable {
    public var cost: CostSummary
    public var inputTokens: UInt64
    public var cacheReadTokens: UInt64
    public var cacheWriteTokens: UInt64
    public var outputTokens: UInt64
    public var reasoningTokens: UInt64
    public var eventCount: Int
    public var incompleteEvents: Int
    public var latestEventMs: Int64?
    public var cacheReadRatio: Double? {
        guard incompleteEvents == 0 else { return nil }
        let input = Double(inputTokens) + Double(cacheReadTokens) + Double(cacheWriteTokens)
        return input == 0 ? nil : Double(cacheReadTokens) / input
    }
}

public struct BreakdownRow: Codable, Identifiable, Sendable {
    public var id: String
    public var label: String
    public var provider: Harness?
    public var parentId: String?
    public var summary: UsageSummary
    public var latestDate: Date? { summary.latestEventMs.map(Date.init(milliseconds:)) }
}

public struct TimelineBucket: Codable, Identifiable, Sendable {
    public var timestampMs: Int64
    public var summary: UsageSummary
    public var id: Int64 { timestampMs }
    public var date: Date { Date(milliseconds: timestampMs) }
}

public struct ObservedState: Codable, Sendable {
    public var provider: Harness
    public var sessionId: String
    public var timestampMs: Int64
    public var kind: String
    public var data: JSONValue
}

/// Metadata-only state; no prompt/response fields are accepted by the native collector.
public enum JSONValue: Codable, Sendable {
    case string(String), number(Double), bool(Bool), object([String: JSONValue]), array([JSONValue]), null
    public init(from decoder: Decoder) throws {
        let c = try decoder.singleValueContainer()
        if c.decodeNil() { self = .null }
        else if let v = try? c.decode(Bool.self) { self = .bool(v) }
        else if let v = try? c.decode(Double.self) { self = .number(v) }
        else if let v = try? c.decode(String.self) { self = .string(v) }
        else if let v = try? c.decode([String: JSONValue].self) { self = .object(v) }
        else { self = .array(try c.decode([JSONValue].self)) }
    }
    public func encode(to encoder: Encoder) throws {
        var c = encoder.singleValueContainer()
        switch self {
        case .null: try c.encodeNil()
        case .string(let v): try c.encode(v)
        case .number(let v): try c.encode(v)
        case .bool(let v): try c.encode(v)
        case .object(let v): try c.encode(v)
        case .array(let v): try c.encode(v)
        }
    }
}

public struct ScanReport: Codable, Sendable {
    public var filesDiscovered: Int
    public var filesChanged: Int
    public var eventsUpserted: Int
    public var checkedAtMs: Int64
    public var warnings: [String]
    public var undatedEvents: Int? = nil
    public var undatedTokens: UInt64? = nil
}

public struct Dashboard: Codable, Sendable {
    public var schemaVersion: Int
    public var summary: UsageSummary
    public var providers: [BreakdownRow]
    public var models: [BreakdownRow]
    public var projects: [BreakdownRow]
    public var sessions: [BreakdownRow]
    public var timeline: [TimelineBucket]
    public var states: [ObservedState]
    public var catalogId: String
    public var catalogRetrievedAt: String
    public var catalogSources: [String]
    public var lastScan: ScanReport?

    public static func decode(_ data: Data) throws -> Dashboard {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        let result = try decoder.decode(Dashboard.self, from: data)
        guard result.schemaVersion == 1 else { throw DashboardError.unsupportedSchema(result.schemaVersion) }
        return result
    }
    public var recentSessions: [BreakdownRow] { sessions.sorted { ($0.summary.latestEventMs ?? 0) > ($1.summary.latestEventMs ?? 0) } }
    public var rootSessions: [BreakdownRow] {
        let ids = Set(sessions.map(\.id))
        let byId = Dictionary(uniqueKeysWithValues: sessions.map { ($0.id, $0) })
        var roots = sessions.filter { $0.parentId == nil || !ids.contains($0.parentId!) }
        var visited = Set(roots.flatMap { taskFamily($0).map(\.id) })
        // Broken parent graphs can contain cycles. Choose a deterministic cycle
        // member as a display root, keeping every task reachable exactly once.
        for row in sessions.sorted(by: { $0.id < $1.id }) where !visited.contains(row.id) {
            var chain: [String] = []
            var current: String? = row.id
            while let id = current, !visited.contains(id) {
                if let cycleStart = chain.firstIndex(of: id) {
                    let rootId = chain[cycleStart...].min()!
                    let root = byId[rootId]!
                    roots.append(root)
                    visited.formUnion(taskFamily(root).map(\.id))
                    break
                }
                chain.append(id)
                current = byId[id]?.parentId
            }
        }
        return roots.sorted {
            let lhs = taskFamily($0).compactMap(\.summary.latestEventMs).max() ?? 0
            let rhs = taskFamily($1).compactMap(\.summary.latestEventMs).max() ?? 0
            return lhs == rhs ? $0.id < $1.id : lhs > rhs
        }
    }
    public func children(of id: String) -> [BreakdownRow] { recentSessions.filter { $0.parentId == id } }
    public func taskFamily(_ row: BreakdownRow) -> [BreakdownRow] {
        var visited = Set<String>()
        var result: [BreakdownRow] = []
        func collect(_ item: BreakdownRow) {
            guard visited.insert(item.id).inserted else { return }
            result.append(item)
            for child in children(of: item.id) { collect(child) }
        }
        collect(row)
        return result
    }
    public func familySummary(_ row: BreakdownRow) -> CostSummary {
        let family = taskFamily(row)
        var total = family[0].summary.cost
        for child in family.dropFirst() { total.add(child.summary.cost) }
        return total
    }
}

public enum DashboardError: Error, LocalizedError {
    case unsupportedSchema(Int)
    public var errorDescription: String? {
        switch self { case .unsupportedSchema(let v): return "Unsupported dashboard schema: \(v)" }
    }
}

public extension Date {
    init(milliseconds: Int64) { self.init(timeIntervalSince1970: Double(milliseconds) / 1000) }
    var milliseconds: Int64 { Int64((timeIntervalSince1970 * 1000).rounded()) }
}

public enum TimeWindow: String, CaseIterable, Identifiable, Sendable {
    case today, week, month
    public var id: Self { self }
    public var localizationKey: String { "period.\(rawValue)" }
    public func interval(now: Date, timeZone: TimeZone) -> DateInterval {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = timeZone
        let start = calendar.startOfDay(for: now)
        let days = self == .today ? 0 : (self == .week ? -6 : -29)
        return DateInterval(start: calendar.date(byAdding: .day, value: days, to: start)!, end: now)
    }
}
