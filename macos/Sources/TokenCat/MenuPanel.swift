import AppKit
import SwiftUI
import TokenCatKit

struct MenuPanel: View {
    @EnvironmentObject private var model: AppModel
    @EnvironmentObject private var settings: AppSettings
    @EnvironmentObject private var settingsWindow: SettingsWindowController
    @Environment(\.openWindow) private var openWindow
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    private var contentHeight: CGFloat? {
        NSScreen.main.map { max(140, min(560, $0.visibleFrame.height - 160)) }
    }

    var body: some View {
        VStack(spacing: 0) {
            header
            Divider()
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    if let snapshot = model.dashboard {
                        summary(snapshot)
                    } else {
                        LoadingOrEmpty().frame(minHeight: 220)
                    }
                }.padding(20)
            }
            // MenuBarExtra asks for the minimum size: a maxHeight-only scroll
            // view is allowed to collapse to zero even when its content is loaded.
            .frame(height: contentHeight)
            Divider()
            footer
        }
        .frame(width: 390)
        .modifier(MenuPanelMaterial())
        .tint(TokenCatTheme.accent)
        .animation(reduceMotion ? nil : .easeInOut(duration: 0.18), value: model.dashboard?.summary.cost.totalTokens)
    }

    private var header: some View {
        let s = settings.strings
        return HStack(spacing: 10) {
            Image(systemName: "cat.fill").font(.title3).foregroundStyle(TokenCatTheme.accent)
            Text(s.text("app.name")).font(.headline)
            Spacer(minLength: 8)
            Picker(s.text("period.title"), selection: $model.window) {
                ForEach(TimeWindow.allCases) { Text(s.text($0.localizationKey)).tag($0) }
            }.pickerStyle(.segmented).controlSize(.small).font(.caption).labelsHidden().frame(width: 175)
                .help(s.text("period.sharedSelection"))
        }.padding(.horizontal, 20).padding(.vertical, 15)
    }

    @ViewBuilder
    private func summary(_ snapshot: Dashboard) -> some View {
        let s = settings.strings
        if model.error != nil {
            Label(s.text("status.retained"), systemImage: "exclamationmark.circle")
                .font(.caption).foregroundStyle(.orange)
        }
        TokenUsageHero(summary: snapshot.summary)
        if snapshot.summary.eventCount == 0 {
            VStack(alignment: .leading, spacing: 12) {
                Text(s.text("usage.noEvents")).font(.subheadline.weight(.medium))
                Text(s.text("usage.emptyDescription")).font(.caption).foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
                Button { settingsWindow.open() } label: { Label(s.text("settings.sources"), systemImage: "folder") }
                    .buttonStyle(.bordered)
            }.padding(.vertical, 12)
        } else {
            if !snapshot.providers.isEmpty {
                Divider()
                VStack(spacing: 12) {
                    SectionHeading(title: s.text("usage.harnesses"))
                    ForEach(s.matchingRows(snapshot.providers, query: "", kind: .provider, sort: .tokens)) { row in
                        providerRow(row, totalTokens: snapshot.summary.cost.totalTokens)
                    }
                }
            }
            if !snapshot.models.isEmpty {
                Divider()
                VStack(spacing: 12) {
                    SectionHeading(title: s.text("usage.topModels"))
                    ForEach(s.matchingRows(snapshot.models, query: "", kind: .model, sort: .tokens).prefix(3)) { row in
                        HStack(spacing: 8) {
                            Image(systemName: row.provider?.symbol ?? "cpu")
                                .foregroundStyle(row.provider?.tint ?? TokenCatTheme.accent).frame(width: 18)
                            Text(s.label(row, kind: .model)).lineLimit(1).help(s.label(row, kind: .model))
                            Spacer(minLength: 6)
                            Text(s.compactCount(row.summary.cost.totalTokens)).monospacedDigit()
                            if snapshot.summary.cost.totalTokens > 0 {
                                Text(s.percent(Double(row.summary.cost.totalTokens) / Double(snapshot.summary.cost.totalTokens)))
                                    .foregroundStyle(.secondary).monospacedDigit().frame(width: 38, alignment: .trailing)
                            }
                        }.font(.subheadline)
                            .help(s.count(row.summary.cost.totalTokens) + " " + s.text("tokens.title") + " · " + s.cost(row.summary.cost))
                    }
                }
            }
            Divider()
            VStack(alignment: .leading, spacing: 12) {
                HStack {
                    SectionHeading(title: s.text("chart.activity"))
                    Text(s.text("tokens.title")).font(.caption2).foregroundStyle(.secondary)
                }
                UsageChart(buckets: snapshot.timeline, compact: true, window: model.window, compactMetric: .tokens)
            }
            if !snapshot.rootSessions.isEmpty {
                Divider()
                VStack(alignment: .leading, spacing: 12) {
                    SectionHeading(title: s.text("usage.recentTasks"))
                    ForEach(snapshot.rootSessions.prefix(2)) { row in recentTask(row, dashboard: snapshot) }
                }
            }
        }
    }

    private func providerRow(_ row: BreakdownRow, totalTokens: UInt64) -> some View {
        let s = settings.strings
        return VStack(spacing: 8) {
            HStack(spacing: 10) {
                Image(systemName: row.provider?.symbol ?? "square.stack")
                    .foregroundStyle(row.provider?.tint ?? TokenCatTheme.accent).frame(width: 18)
                VStack(alignment: .leading, spacing: 4) {
                    Text(s.label(row, kind: .provider)).font(.subheadline.weight(.medium))
                    Text(s.eventCount(row.summary.eventCount)).font(.caption2).foregroundStyle(.secondary)
                }
                Spacer(minLength: 8)
                VStack(alignment: .trailing, spacing: 4) {
                    Text(s.compactCount(row.summary.cost.totalTokens) + " " + s.text("tokens.title"))
                        .font(.subheadline.weight(.medium))
                    Text(s.cost(row.summary.cost, compact: true)).font(.caption2).foregroundStyle(.secondary)
                }.monospacedDigit()
            }
            if totalTokens > 0 {
                ProgressView(value: Double(row.summary.cost.totalTokens), total: Double(totalTokens))
                    .controlSize(.small)
                    .tint(row.provider?.tint ?? TokenCatTheme.accent)
                    .accessibilityLabel(s.label(row, kind: .provider) + ", " + s.text("tokens.share"))
                    .accessibilityValue(s.percent(Double(row.summary.cost.totalTokens) / Double(totalTokens)))
                    .help(s.text("tokens.share"))
            }
        }
    }

    private var footer: some View {
        let s = settings.strings
        return VStack(spacing: 12) {
            HStack(spacing: 14) {
                Button {
                    openWindow(id: "dashboard")
                    NSApp.activate(ignoringOtherApps: true)
                } label: {
                    Label(s.text("action.dashboard"), systemImage: "arrow.up.right.square")
                        .font(.subheadline.weight(.medium))
                }.buttonStyle(.plain).foregroundStyle(TokenCatTheme.accent)
                Spacer()
                Button { model.requestRefresh() } label: { Image(systemName: "arrow.clockwise").frame(width: 22, height: 22) }
                    .buttonStyle(.plain).disabled(model.refreshing)
                    .help(s.text("action.refresh")).accessibilityLabel(s.text("accessibility.refresh"))
                Button { settingsWindow.open() } label: { Image(systemName: "gearshape").frame(width: 22, height: 22) }
                    .buttonStyle(.plain).help(s.text("action.settings")).accessibilityLabel(s.text("action.settings"))
                    .keyboardShortcut(",", modifiers: .command)
                Menu {
                    Button(s.text("action.quit")) { NSApp.terminate(nil) }.keyboardShortcut("q")
                } label: { Image(systemName: "ellipsis").frame(width: 18, height: 22) }
                    .menuStyle(.borderlessButton).menuIndicator(.hidden).fixedSize()
                    .help(s.text("action.more")).accessibilityLabel(s.text("action.more"))
            }
            StatusFooter(dashboard: model.dashboard)
        }.padding(.horizontal, 20).padding(.vertical, 14)
    }

    private func recentTask(_ row: BreakdownRow, dashboard: Dashboard) -> some View {
        let s = settings.strings
        let family = dashboard.taskFamily(row)
        return Button {
            model.openTask(row.id, window: model.window)
            openWindow(id: "dashboard")
            NSApp.activate(ignoringOtherApps: true)
        } label: {
            HStack(spacing: 10) {
                VStack(alignment: .leading, spacing: 4) {
                    Text(s.label(row, kind: .session)).font(.subheadline).lineLimit(1)
                    HStack(spacing: 5) {
                        if let harness = row.provider { Text(harness.label) }
                        if let date = family.compactMap(\.latestDate).max() { Text(s.relative(date)) }
                        if family.count > 1 { Text(s.text("usage.includesSubtasks")) }
                    }.font(.caption2).foregroundStyle(.secondary).lineLimit(1)
                }
                Spacer(minLength: 4)
                Text(s.cost(dashboard.familySummary(row), compact: true))
                    .font(.subheadline).monospacedDigit().help(s.text("usage.familyCost"))
                Image(systemName: "chevron.right").font(.caption2).foregroundStyle(.tertiary)
            }.contentShape(Rectangle())
        }.buttonStyle(.plain)
    }
}
