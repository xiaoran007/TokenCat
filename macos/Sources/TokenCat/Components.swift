import SwiftUI
import Charts
import TokenCatKit

extension Harness {
    var tint: Color { self == .codex ? .indigo : .orange }
}

struct SectionHeading: View {
    let title: String
    var body: some View {
        Text(title).font(.subheadline.weight(.semibold)).foregroundStyle(.secondary)
            .frame(maxWidth: .infinity, alignment: .leading)
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
                    Label(s.format("cost.unpriced", summary.cost.unpricedEvents), systemImage: "exclamationmark.circle")
                        .font(.caption).foregroundStyle(.orange)
                }
                if summary.cost.hasRange { Text(s.text("cost.rangeExplanation")).font(.caption).foregroundStyle(.secondary) }
            }
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .help(s.text("cost.explanation"))
        .accessibilityLabel(s.format("accessibility.todayCost", s.cost(summary.cost)))
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
    @EnvironmentObject private var settings: AppSettings
    var body: some View {
        let s = settings.strings
        Chart(buckets) { bucket in
            BarMark(x: .value(s.text("chart.time"), bucket.date), y: .value(s.text("chart.cost"), bucket.summary.cost.minUsd))
                .foregroundStyle(Color.accentColor.gradient).cornerRadius(2)
            if bucket.summary.cost.hasRange {
                RuleMark(x: .value(s.text("chart.time"), bucket.date),
                         yStart: .value(s.text("chart.cost"), bucket.summary.cost.minUsd),
                         yEnd: .value(s.text("chart.cost"), bucket.summary.cost.maxUsd))
                    .foregroundStyle(.secondary).lineStyle(StrokeStyle(lineWidth: 1.5))
            }
        }
        .chartXAxis {
            AxisMarks(values: .automatic(desiredCount: compact ? 4 : 7)) { _ in
                if let first = buckets.first, let last = buckets.last, last.date.timeIntervalSince(first.date) > 3 * 86400 {
                    AxisValueLabel(format: .dateTime.month(.abbreviated).day())
                } else { AxisValueLabel(format: .dateTime.hour(.defaultDigits(amPM: .abbreviated))) }
            }
        }
        .chartYAxis {
            AxisMarks(position: .leading, values: .automatic(desiredCount: 3)) {
                AxisGridLine().foregroundStyle(.quaternary)
                if !compact { AxisValueLabel(format: .currency(code: "USD").precision(.fractionLength(2)).locale(s.locale)) }
            }
        }
        .chartYScale(domain: .automatic(includesZero: true))
        .frame(height: compact ? 72 : 190)
        .accessibilityLabel(s.text("usage.trend"))
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
            Circle().fill(model.error == nil ? (dashboard?.lastScan?.warnings.isEmpty == false ? Color.orange : Color.green) : Color.orange).frame(width: 5, height: 5)
            if let scan = dashboard?.lastScan {
                Text(s.format("status.checked", s.relative(Date(milliseconds: scan.checkedAtMs)))).lineLimit(1)
            } else { Text(s.text("status.neverChecked")) }
            Spacer(minLength: 4)
            if model.refreshing { ProgressView().controlSize(.mini).frame(width: 14) }
            if model.error != nil || dashboard?.lastScan?.warnings.isEmpty == false {
                Button { showStatus = true } label: { Image(systemName: "exclamationmark.circle") }.buttonStyle(.plain)
                    .help(s.text("status.warnings"))
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
                    ForEach(s.collectionDiagnostics(scan.warnings, showPaths: settings.showPaths), id: \.self) {
                        Text($0).font(.caption).foregroundStyle(.secondary).textSelection(.enabled)
                    }
                }
            }.padding(18).frame(width: 360)
        }
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
