import SwiftUI
import Charts
import TokenCatKit

enum TokenCatTheme {
    static let accent = Color(nsColor: NSColor(name: "TokenCatAccent") { appearance in
        appearance.bestMatch(from: [.darkAqua, .aqua]) == .darkAqua
            ? NSColor(srgbRed: 0.36, green: 0.78, blue: 0.73, alpha: 1)
            : NSColor(srgbRed: 0.08, green: 0.48, blue: 0.46, alpha: 1)
    })
}

struct SurfaceCard<Content: View>: View {
    let content: Content

    init(@ViewBuilder content: () -> Content) {
        self.content = content()
    }

    var body: some View {
        content
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(18)
            .background(Color(nsColor: .controlBackgroundColor), in: RoundedRectangle(cornerRadius: 14))
            .overlay(RoundedRectangle(cornerRadius: 14).strokeBorder(.primary.opacity(0.07), lineWidth: 1))
    }
}

extension Harness {
    var tint: Color {
        switch self {
        case .codex: .indigo
        case .claude: .orange
        case .opencode: .blue
        case .antigravity: .purple
        }
    }
}

struct SectionHeading: View {
    let title: String
    var body: some View {
        Text(title).font(.subheadline.weight(.semibold)).foregroundStyle(.secondary)
            .frame(maxWidth: .infinity, alignment: .leading)
    }
}

struct TokenUsageHero: View {
    let summary: UsageSummary
    @EnvironmentObject private var settings: AppSettings
    @State private var showDetails = false

    var body: some View {
        let s = settings.strings
        VStack(alignment: .leading, spacing: 10) {
            Text(s.text("tokens.total")).font(.caption.weight(.medium))
                .textCase(.uppercase).tracking(0.8).foregroundStyle(.secondary)
            ViewThatFits(in: .horizontal) {
                HStack(alignment: .firstTextBaseline, spacing: 12) {
                    abbreviatedCount
                    exactCount
                }.fixedSize(horizontal: true, vertical: false)
                VStack(alignment: .leading, spacing: 4) {
                    abbreviatedCount
                    exactCount
                }
            }
            .help(s.text("tokens.reportedOnly"))
            .accessibilityElement(children: .ignore)
            .accessibilityLabel(s.text("tokens.total") + ", " + s.count(summary.cost.totalTokens))
            Button { showDetails.toggle() } label: {
                HStack(alignment: .firstTextBaseline, spacing: 6) {
                    Text(s.cost(summary.cost, compact: true)).font(.title3.weight(.medium)).monospacedDigit()
                    Text(s.text("cost.apiEquivalent")).font(.caption)
                    Image(systemName: "info.circle").font(.caption)
                }.foregroundStyle(.secondary)
            }.buttonStyle(.plain).help(s.text("cost.explanation"))
                .accessibilityLabel(s.text("cost.apiEquivalent") + ", " + s.cost(summary.cost))
                .accessibilityHint(s.text("cost.details"))
            Text(s.eventCount(summary.eventCount)).font(.caption).foregroundStyle(.secondary)
            if summary.cost.unpricedEvents > 0 {
                Label(s.format("cost.unpriced", summary.cost.unpricedEvents), systemImage: "info.circle")
                    .font(.caption).foregroundStyle(.secondary)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .popover(isPresented: $showDetails, arrowEdge: .trailing) {
            CostBreakdown(summary: summary).padding(20).frame(width: 350).environmentObject(settings)
        }
    }

    private var abbreviatedCount: some View {
        Text(settings.strings.compactCount(summary.cost.totalTokens))
            .font(.system(size: 44, weight: .semibold, design: .rounded))
            .monospacedDigit().contentTransition(.numericText())
            .lineLimit(1).minimumScaleFactor(0.5)
    }

    @ViewBuilder
    private var exactCount: some View {
        if summary.cost.totalTokens >= 1_000 {
            Text(settings.strings.count(summary.cost.totalTokens))
                .font(.subheadline).monospacedDigit().foregroundStyle(.secondary)
                .textSelection(.enabled)
        }
    }
}

struct CostHero: View {
    let summary: UsageSummary
    let compact: Bool
    var titleKey = "cost.apiEquivalent"
    @EnvironmentObject private var settings: AppSettings
    @State private var showDetails = false
    var body: some View {
        let s = settings.strings
        Button { showDetails.toggle() } label: {
            VStack(alignment: .leading, spacing: compact ? 6 : 10) {
                HStack {
                    Text(s.text(titleKey)).font(.subheadline).foregroundStyle(.secondary)
                    Image(systemName: "info.circle").font(.caption).foregroundStyle(.tertiary)
                    Spacer(minLength: 0)
                }
                Text(s.cost(summary.cost, compact: true))
                    .font(.system(size: compact ? 35 : 44, weight: .semibold, design: .rounded))
                    .monospacedDigit().contentTransition(.numericText())
                    .minimumScaleFactor(0.6).lineLimit(1)
                    .foregroundStyle(.primary)
                HStack(spacing: 12) {
                    Text(s.eventCount(summary.eventCount))
                    if let ratio = summary.cacheReadRatio {
                        Text(s.text("cache.ratio") + " " + s.percent(ratio))
                            .help(s.text("cache.explanation"))
                    }
                }.font(.caption).foregroundStyle(.secondary)
                if summary.cost.unpricedEvents > 0 {
                    Label(s.format("cost.unpriced", summary.cost.unpricedEvents), systemImage: "info.circle")
                        .font(.caption).foregroundStyle(.secondary)
                }
                if summary.cost.hasRange { Text(s.text("cost.rangeExplanation")).font(.caption).foregroundStyle(.secondary) }
            }
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .help(s.text("cost.explanation"))
        .accessibilityLabel(s.text(titleKey) + ", " + s.cost(summary.cost))
        .accessibilityHint(s.text("cost.details"))
        .popover(isPresented: $showDetails, arrowEdge: .trailing) {
            CostBreakdown(summary: summary).padding(20).frame(width: 350)
                .environmentObject(settings)
        }
    }
}

struct CostBreakdown: View {
    let summary: UsageSummary
    @EnvironmentObject private var settings: AppSettings
    var body: some View {
        let s = settings.strings
        VStack(alignment: .leading, spacing: 14) {
            Text(s.text("cost.details")).font(.headline)
            Text(s.text("cost.explanation")).font(.caption).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
            if summary.cost.hasRange {
                Text(s.text("cost.rangeExplanation")).font(.caption).foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Divider()
            Text(s.text("tokens.reportedOnly")).font(.caption).foregroundStyle(.secondary)
            costRow("cost.input", summary.inputTokens, summary.cost.inputUsd, summary.cost.inputUsd)
            costRow("cost.cacheRead", summary.cacheReadTokens, summary.cost.cacheReadUsd, summary.cost.cacheReadUsd)
            costRow("cost.cacheWrite", summary.cacheWriteTokens, summary.cost.cacheWriteMinUsd, summary.cost.cacheWriteMaxUsd)
            costRow("cost.output", summary.outputTokens, summary.cost.outputUsd, summary.cost.outputUsd)
            if summary.reasoningTokens > 0 {
                HStack { Text(s.text("cost.reasoning")); Spacer(); Text(s.count(summary.reasoningTokens)).monospacedDigit() }
                    .font(.caption).foregroundStyle(.secondary)
            }
            Divider()
            if let coverage = summary.cost.coverage { Text(s.format("cost.coverage", s.percent(coverage))).font(.caption).foregroundStyle(.secondary) }
            if summary.cost.uncertainEvents > 0 { Text(s.format("cost.uncertain", summary.cost.uncertainEvents)).font(.caption).foregroundStyle(.secondary) }
            if summary.incompleteEvents > 0 { Text(s.format("usage.incomplete", summary.incompleteEvents)).font(.caption).foregroundStyle(.orange) }
            if !summary.cost.unknownModels.isEmpty {
                Text(s.text("cost.unknownModels")).font(.caption.weight(.semibold))
                Text(summary.cost.unknownModels.joined(separator: ", ")).font(.caption).textSelection(.enabled)
            }
            if let matches = summary.cost.pricingMatches, !matches.isEmpty {
                DisclosureGroup(s.text("cost.matches")) {
                    ScrollView {
                        VStack(alignment: .leading, spacing: 10) {
                            ForEach(matches, id: \.self) { match in
                                VStack(alignment: .leading, spacing: 3) {
                                    Text(match.model).font(.caption.weight(.medium))
                                    Text(match.pricedModel + " · " + match.source).font(.caption2).textSelection(.enabled)
                                    Text(s.text("cost.match." + match.kind)).font(.caption2).foregroundStyle(.secondary)
                                }.frame(maxWidth: .infinity, alignment: .leading)
                            }
                        }
                    }.frame(maxHeight: 180)
                }.font(.caption)
            }
        }
    }
    private func costRow(_ key: String, _ tokens: UInt64, _ min: Double, _ max: Double) -> some View {
        let s = settings.strings
        return HStack(alignment: .firstTextBaseline) {
            VStack(alignment: .leading, spacing: 3) {
                Text(s.text(key)).font(.subheadline)
                Text(s.count(tokens) + " " + s.text("tokens.title")).font(.caption).foregroundStyle(.secondary)
            }
            Spacer()
            Text(s.categoryCost(tokens: tokens, min: min, max: max, hasUnpriced: summary.cost.unpricedEvents > 0))
                .font(.subheadline).monospacedDigit()
        }
    }
}

struct UsageChart: View {
    let buckets: [TimelineBucket]
    var compact = false
    var window: TimeWindow = .today
    var compactMetric: Metric = .cost
    @EnvironmentObject private var settings: AppSettings
    @State private var metric: Metric = .cost
    @State private var selectedDate: Date?

    enum Metric: String, CaseIterable {
        case cost, tokens
        var key: String { "chart.\(rawValue)" }
    }

    private var activeMetric: Metric { compact ? compactMetric : metric }
    private var component: Calendar.Component { window == .today ? .hour : .day }
    private var hasValues: Bool {
        buckets.contains { bucket in
            activeMetric == .tokens
                ? bucket.summary.cost.totalTokens > 0
                : bucket.summary.cost.pricedTokens > 0 || bucket.summary.cost.maxUsd > 0
        }
    }

    var body: some View {
        let s = settings.strings
        VStack(alignment: .leading, spacing: compact ? 8 : 14) {
            if !compact {
                HStack {
                    Text(s.text("chart.activity")).font(.subheadline.weight(.semibold))
                    Spacer()
                    Picker(s.text("chart.metric"), selection: $metric) {
                        ForEach(Metric.allCases, id: \.self) { Text(s.text($0.key)).tag($0) }
                    }.pickerStyle(.segmented).frame(width: 190)
                }
            }
            if let timeZone = settings.timeZone {
                if hasValues {
                    plot(timeZone: timeZone)
                    if !compact { selectionDetail(timeZone: timeZone) }
                } else { emptyChart }
            } else {
                Text(s.text("settings.invalidTimezone")).font(.caption).foregroundStyle(.secondary)
            }
        }
        .onChange(of: window) { _, _ in selectedDate = nil }
        .onChange(of: metric) { _, _ in selectedDate = nil }
    }

    private var emptyChart: some View {
        let s = settings.strings
        let hasEvents = buckets.contains { $0.summary.eventCount > 0 }
        let descriptionKey = hasEvents
            ? (activeMetric == .cost ? "chart.unpricedDescription" : "tokens.reportedOnly")
            : "usage.emptyDescription"
        return VStack(alignment: compact ? .leading : .center, spacing: 8) {
            if !compact { Image(systemName: "chart.bar.xaxis").font(.title2).foregroundStyle(TokenCatTheme.accent) }
            Text(s.text(activeMetric == .tokens ? "chart.noTokens" : "chart.empty"))
                .font(.subheadline.weight(.medium))
            if !compact || hasEvents {
                Text(s.text(descriptionKey))
                    .font(.caption).foregroundStyle(.secondary).multilineTextAlignment(compact ? .leading : .center)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .frame(maxWidth: .infinity, minHeight: compact ? 48 : 190, alignment: compact ? .leading : .center)
    }

    private func plot(timeZone: TimeZone) -> some View {
        let s = settings.strings
        let calendar = calendar(in: timeZone)
        return Chart {
            ForEach(buckets) { bucket in
                if activeMetric == .tokens || bucket.summary.cost.pricedTokens > 0 || bucket.summary.cost.maxUsd > 0 {
                    BarMark(x: .value(s.text("chart.time"), bucket.date, unit: component, calendar: calendar),
                            y: .value(s.text(activeMetric.key), value(for: bucket)))
                        .foregroundStyle(TokenCatTheme.accent.gradient).cornerRadius(compact ? 2 : 4)
                        .opacity(selectedBucket(in: calendar).map { $0.id == bucket.id ? 1 : 0.45 } ?? 1)
                        .accessibilityLabel(periodLabel(bucket.date, timeZone: timeZone))
                        .accessibilityValue(valueLabel(for: bucket))
                    if activeMetric == .cost && bucket.summary.cost.hasRange {
                        RuleMark(x: .value(s.text("chart.time"), bucket.date, unit: component, calendar: calendar),
                                 yStart: .value(s.text("chart.cost"), bucket.summary.cost.minUsd),
                                 yEnd: .value(s.text("chart.cost"), bucket.summary.cost.maxUsd))
                            .foregroundStyle(TokenCatTheme.accent).lineStyle(StrokeStyle(lineWidth: 1.5))
                    }
                }
            }
            if let selected = selectedBucket(in: calendar) {
                RuleMark(x: .value(s.text("chart.time"), selected.date, unit: component, calendar: calendar))
                    .foregroundStyle(.secondary.opacity(0.5)).lineStyle(StrokeStyle(lineWidth: 1, dash: [3, 3]))
            }
        }
        .chartXAxis {
            AxisMarks(values: .automatic(desiredCount: compact ? 4 : 6)) { value in
                AxisValueLabel {
                    if let date = value.as(Date.self) { Text(axisLabel(date, timeZone: timeZone)) }
                }
            }
        }
        .chartYAxis {
            AxisMarks(position: .leading, values: .automatic(desiredCount: 3)) { value in
                AxisGridLine().foregroundStyle(.quaternary)
                if !compact {
                    AxisValueLabel {
                        if let number = value.as(Double.self) {
                            Text(activeMetric == .cost ? s.money(number, compact: true) : number.formatted(.number.notation(.compactName).locale(s.locale)))
                        }
                    }
                }
            }
        }
        .chartXScale(domain: domain(in: calendar))
        .chartYScale(domain: .automatic(includesZero: true))
        .chartOverlay { proxy in
            GeometryReader { geometry in
                Rectangle().fill(.clear).contentShape(Rectangle())
                    .onContinuousHover { phase in
                        switch phase {
                        case .active(let location): select(at: location, proxy: proxy, geometry: geometry)
                        case .ended: selectedDate = nil
                        }
                    }
                    .onTapGesture { location in select(at: location, proxy: proxy, geometry: geometry) }
            }
        }
        .frame(height: compact ? 78 : 190)
        .accessibilityLabel(s.text(activeMetric == .cost ? "usage.trend" : "tokens.total"))
    }

    private func selectionDetail(timeZone: TimeZone) -> some View {
        let s = settings.strings
        return HStack(alignment: .firstTextBaseline, spacing: 12) {
            if let bucket = selectedBucket(in: calendar(in: timeZone)) {
                Text(periodLabel(bucket.date, timeZone: timeZone)).foregroundStyle(.secondary)
                Spacer(minLength: 4)
                Text(valueLabel(for: bucket)).fontWeight(.medium).monospacedDigit()
                Text(s.eventCount(bucket.summary.eventCount)).foregroundStyle(.secondary)
            } else {
                Text(s.text("chart.inspect")).foregroundStyle(.secondary)
                Spacer(minLength: 0)
            }
        }.font(.caption).frame(minHeight: 18)
    }

    private func calendar(in timeZone: TimeZone) -> Calendar {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = timeZone
        return calendar
    }

    private func domain(in calendar: Calendar) -> ClosedRange<Date> {
        let dates = buckets.map(\.date)
        let first = calendar.dateInterval(of: component, for: dates.min()!)!.start
        let last = calendar.dateInterval(of: component, for: dates.max()!)!.end
        return first...last
    }

    private func selectedBucket(in calendar: Calendar) -> TimelineBucket? {
        guard let selectedDate else { return nil }
        return buckets.first { calendar.isDate($0.date, equalTo: selectedDate, toGranularity: component) }
    }

    private func select(at location: CGPoint, proxy: ChartProxy, geometry: GeometryProxy) {
        guard let plotFrame = proxy.plotFrame, geometry[plotFrame].contains(location) else {
            selectedDate = nil
            return
        }
        selectedDate = proxy.value(atX: location.x - geometry[plotFrame].minX, as: Date.self)
    }

    private func value(for bucket: TimelineBucket) -> Double {
        activeMetric == .cost ? bucket.summary.cost.minUsd : Double(bucket.summary.cost.totalTokens)
    }

    private func valueLabel(for bucket: TimelineBucket) -> String {
        let s = settings.strings
        return activeMetric == .cost ? s.cost(bucket.summary.cost) : s.count(bucket.summary.cost.totalTokens) + " " + s.text("tokens.title")
    }

    private func axisLabel(_ date: Date, timeZone: TimeZone) -> String {
        let style = Date.FormatStyle(locale: settings.strings.locale, timeZone: timeZone)
        return date.formatted(window == .today ? style.hour(.defaultDigits(amPM: .abbreviated)) : style.month(.abbreviated).day())
    }

    private func periodLabel(_ date: Date, timeZone: TimeZone) -> String {
        let style = Date.FormatStyle(locale: settings.strings.locale, timeZone: timeZone).month(.abbreviated).day()
        return date.formatted(window == .today ? style.hour(.defaultDigits(amPM: .abbreviated)).minute() : style)
    }
}

struct HarnessRow: View {
    let row: BreakdownRow
    @EnvironmentObject private var settings: AppSettings
    var body: some View {
        let s = settings.strings
        HStack(spacing: 11) {
            Image(systemName: row.provider?.symbol ?? "square.stack").font(.body.weight(.medium))
                .foregroundStyle(row.provider?.tint ?? .accentColor).frame(width: 28, height: 28)
                .background((row.provider?.tint ?? .accentColor).opacity(0.1), in: RoundedRectangle(cornerRadius: 7))
            VStack(alignment: .leading, spacing: 3) {
                Text(s.label(row, kind: .provider)).font(.subheadline.weight(.medium))
                Text(s.eventCount(row.summary.eventCount)).font(.caption).foregroundStyle(.secondary)
            }
            Spacer()
            VStack(alignment: .trailing, spacing: 3) {
                Text(s.cost(row.summary.cost, compact: true)).font(.subheadline.weight(.medium)).monospacedDigit()
                Text(s.compactCount(row.summary.cost.totalTokens) + " " + s.text("tokens.title")).font(.caption).foregroundStyle(.secondary)
            }
        }
    }
}

struct StatusFooter: View {
    let dashboard: Dashboard?
    @EnvironmentObject private var model: AppModel
    @EnvironmentObject private var settings: AppSettings
    @State private var showStatus = false
    var body: some View {
        let s = settings.strings
        HStack(spacing: 7) {
            Circle().fill(statusColor).frame(width: 5, height: 5).accessibilityHidden(true)
            if model.error != nil {
                Text(s.text("status.error")).lineLimit(1)
            } else if let scan = dashboard?.lastScan {
                Text(s.format("status.checked", s.relative(Date(milliseconds: scan.checkedAtMs)))).lineLimit(1)
            } else { Text(s.text("status.neverChecked")) }
            Spacer(minLength: 4)
            if model.refreshing { ProgressView().controlSize(.mini).frame(width: 14) }
            if model.error != nil || dashboard?.lastScan?.warnings.isEmpty == false || (dashboard?.lastScan?.undatedEvents ?? 0) > 0 {
                Button { showStatus = true } label: { Image(systemName: "info.circle") }.buttonStyle(.plain)
                    .help(s.text("status.warnings")).accessibilityLabel(s.text("status.warnings"))
            }
        }
        .font(.caption2).foregroundStyle(.secondary)
        .popover(isPresented: $showStatus) {
            VStack(alignment: .leading, spacing: 10) {
                Text(s.text("status.warnings")).font(.headline)
                if let error = model.error {
                    if settings.showPaths { Text(error).font(.caption).textSelection(.enabled) }
                    else { Text(s.text("status.error")).font(.caption) }
                }
                if let scan = dashboard?.lastScan {
                    Text(s.format("status.sources", scan.filesDiscovered)).font(.caption)
                    if let undated = scan.undatedEvents, undated > 0 {
                        Text(s.format("status.undated", undated)).font(.caption).foregroundStyle(.secondary)
                    }
                    ForEach(s.collectionDiagnostics(scan.warnings, showPaths: settings.showPaths), id: \.self) {
                        Text($0).font(.caption).foregroundStyle(.secondary).textSelection(.enabled)
                    }
                }
            }.padding(18).frame(width: 360)
        }
    }

    private var statusColor: Color {
        if model.error != nil || dashboard?.lastScan?.warnings.isEmpty == false { return .orange }
        return dashboard?.lastScan == nil ? .secondary : .green
    }
}

struct LoadingOrEmpty: View {
    @EnvironmentObject private var model: AppModel
    @EnvironmentObject private var settings: AppSettings
    var body: some View {
        let s = settings.strings
        VStack(spacing: 12) {
            if let error = model.error {
                Image(systemName: "exclamationmark.triangle").font(.title).foregroundStyle(.orange)
                Text(s.text("status.error")).font(.headline)
                DisclosureGroup(s.text("status.warnings")) {
                    if settings.showPaths { Text(error).font(.caption).foregroundStyle(.secondary).textSelection(.enabled) }
                    else { Text(s.text("status.privateDiagnostics")).font(.caption).foregroundStyle(.secondary) }
                }.font(.caption)
                Button(s.text("action.retry")) { model.requestRefresh() }
            } else {
                ProgressView().controlSize(.small)
                Text(s.text("status.starting")).font(.subheadline).foregroundStyle(.secondary)
            }
        }.frame(maxWidth: .infinity).padding(30)
    }
}
