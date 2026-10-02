import Foundation

public enum AppLanguage: String, CaseIterable, Identifiable, Sendable {
    case system, english = "en-US", simplifiedChinese = "zh-Hans"
    public var id: Self { self }
    public var nativeName: String {
        switch self { case .system: return "language.system"; case .english: return "English (US)"; case .simplifiedChinese: return "简体中文" }
    }
    public var resolved: String {
        if self != .system { return rawValue }
        let match = Bundle.preferredLocalizations(from: ["en-US", "zh-Hans"], forPreferences: Locale.preferredLanguages).first!
        return match
    }
    public var locale: Locale { Locale(identifier: resolved) }
}

public struct Localizer: Sendable {
    public let language: AppLanguage
    public init(_ language: AppLanguage = .system) { self.language = language }
    public var locale: Locale { language.locale }
    public func text(_ key: String) -> String {
        let path = Bundle.module.path(forResource: language.resolved, ofType: "lproj")!
        return Bundle(path: path)!.localizedString(forKey: key, value: nil, table: nil)
    }
    public func format(_ key: String, _ arguments: CVarArg...) -> String {
        String(format: text(key), locale: locale, arguments: arguments)
    }
    public func eventCount(_ count: Int) -> String {
        format("events.count", count)
    }
    public func count(_ value: UInt64) -> String { value.formatted(.number.locale(locale)) }
    public func compactCount(_ value: UInt64) -> String { value.formatted(.number.notation(.compactName).locale(locale)) }
    public func percent(_ value: Double) -> String { value.formatted(.percent.precision(.fractionLength(0)).locale(locale)) }
    public func money(_ value: Double, compact: Bool = false) -> String {
        if value > 0 && value < 0.0001 {
            return format("cost.lessThan", money(0.0001))
        }
        if compact && (value == 0 || abs(value) >= 0.01) {
            return value.formatted(.currency(code: "USD").precision(.fractionLength(2)).locale(locale))
        }
        return value.formatted(.currency(code: "USD").precision(.fractionLength(2...4)).locale(locale))
    }
    public func cost(_ value: CostSummary, compact: Bool = false) -> String {
        if value.unpricedEvents > 0 && value.pricedTokens == 0 { return text("cost.unavailable") }
        let amount = value.hasRange
            ? format("cost.range", money(value.minUsd, compact: compact), money(value.maxUsd, compact: compact))
            : money(value.minUsd, compact: compact)
        return value.unpricedEvents > 0 ? format("cost.knownAmount", amount) : amount
    }
    public func categoryCost(tokens: UInt64, min: Double, max: Double, hasUnpriced: Bool) -> String {
        if tokens > 0 && max == 0 && hasUnpriced { return text("cost.unavailable") }
        let amount = min == max ? money(min) : format("cost.range", money(min), money(max))
        return tokens > 0 && hasUnpriced ? format("cost.knownAmount", amount) : amount
    }
    public func label(_ row: BreakdownRow, kind: BreakdownKind) -> String {
        if kind == .provider, let harness = row.provider { return harness.label }
        if row.label.hasPrefix("session:") { return format("usage.anonymousSession", String(row.label.dropFirst(8))) }
        if row.label.hasPrefix("project:") { return format("usage.anonymousProject", String(row.label.dropFirst(8))) }
        if row.id == "unknown" { return text(kind == .project ? "usage.unattributedProject" : "usage.unknownModel") }
        return row.label
    }
    public func collectionDiagnostics(_ warnings: [String], showPaths: Bool) -> [String] {
        if showPaths { return warnings }
        return warnings.isEmpty ? [] : [format("status.warningCount", warnings.count), text("status.privateDiagnostics")]
    }
    public func relative(_ date: Date, now: Date = Date()) -> String {
        let formatter = RelativeDateTimeFormatter()
        formatter.locale = locale
        formatter.unitsStyle = .short
        return formatter.localizedString(for: date, relativeTo: now)
    }
    public static func resourceKeys(_ language: AppLanguage) -> Set<String> {
        let path = Bundle.module.path(forResource: "Localizable", ofType: "strings", inDirectory: "\(language.resolved).lproj")!
        let strings = NSDictionary(contentsOfFile: path) as! [String: String]
        let pluralsPath = Bundle.module.path(forResource: "Localizable", ofType: "stringsdict", inDirectory: "\(language.resolved).lproj")!
        let plurals = NSDictionary(contentsOfFile: pluralsPath) as! [String: Any]
        return Set(strings.keys).union(plurals.keys)
    }
}
