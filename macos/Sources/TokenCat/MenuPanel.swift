import AppKit
import SwiftUI
import TokenCatKit

struct MenuPanel: View {
    @EnvironmentObject private var model: AppModel
    @EnvironmentObject private var settings: AppSettings
    @Environment(\.openWindow) private var openWindow
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    private var contentHeight: CGFloat? {
        NSScreen.main.map { max(140, min(520, $0.visibleFrame.height - 180)) }
    }

    var body: some View {
        let s = settings.strings
        VStack(alignment: .leading, spacing: 0) {
            header
            Divider()
            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    if let today = model.today {
                        SurfaceCard {
                            VStack(alignment: .leading, spacing: 16) {
                                CostHero(summary: today.summary, compact: true)
                                UsageChart(buckets: today.timeline, compact: true)
                            }
                        }
                        if !today.providers.isEmpty {
                            VStack(alignment: .leading, spacing: 12) {
                                SectionHeading(title: s.text("usage.harnesses"))
                                ForEach(today.providers) { HarnessRow(row: $0) }
                            }.padding(.horizontal, 2)
                        }
                        if let quota = today.states.filter({ $0.kind == "quota" }).max(by: { $0.timestampMs < $1.timestampMs }) {
                            SurfaceCard { QuotaObservationView(observation: quota) }
                        }
                        if today.summary.eventCount == 0 {
                            Text(s.text("usage.emptyDescription")).font(.caption).foregroundStyle(.secondary)
                                .fixedSize(horizontal: false, vertical: true).padding(.horizontal, 2)
                        }
                        if !today.rootSessions.isEmpty {
                            VStack(alignment: .leading, spacing: 12) {
                                SectionHeading(title: s.text("usage.recentTasks"))
                                ForEach(today.rootSessions.prefix(3)) { row in recentTask(row, dashboard: today) }
                            }.padding(.horizontal, 2)
                        }
                    } else { LoadingOrEmpty() }
                }.padding(16)
            }.frame(height: contentHeight)
            Divider()
            footer
        }
        .frame(width: 390)
        .tint(TokenCatTheme.accent)
        .animation(reduceMotion ? nil : .easeInOut(duration: 0.18), value: model.today?.summary.cost.minUsd)
    }

    private var header: some View {
        let s = settings.strings
        return HStack(spacing: 10) {
            Image(systemName: "cat.fill").font(.title3).foregroundStyle(TokenCatTheme.accent)
                .frame(width: 34, height: 34)
                .background(TokenCatTheme.accent.opacity(0.1), in: RoundedRectangle(cornerRadius: 10))
            VStack(alignment: .leading, spacing: 2) {
                Text(s.text("app.name")).font(.headline)
                Text(s.text("app.tagline")).font(.caption2).foregroundStyle(.secondary)
            }
            Spacer(minLength: 4)
            Text(s.text("period.today")).font(.caption.weight(.medium)).foregroundStyle(.secondary)
            Button { model.requestRefresh() } label: { Image(systemName: "arrow.clockwise").frame(width: 24, height: 24) }
                .buttonStyle(.borderless).help(s.text("action.refresh"))
                .disabled(model.refreshing).accessibilityLabel(s.text("accessibility.refresh"))
        }.padding(.horizontal, 16).padding(.vertical, 14)
    }

    private var footer: some View {
        let s = settings.strings
        return VStack(spacing: 12) {
            StatusFooter(dashboard: model.today)
            HStack(spacing: 10) {
                Button {
                    openWindow(id: "dashboard")
                    NSApp.activate(ignoringOtherApps: true)
                } label: {
                    Label(s.text("action.dashboard"), systemImage: "rectangle.grid.2x2")
                        .frame(maxWidth: .infinity)
                }.buttonStyle(.borderedProminent).controlSize(.large)
                SettingsLink { Image(systemName: "gearshape").frame(width: 20, height: 20) }
                    .buttonStyle(.bordered).controlSize(.large)
                    .help(s.text("action.settings")).accessibilityLabel(s.text("action.settings"))
                Menu {
                    Button(s.text("action.quit")) { NSApp.terminate(nil) }.keyboardShortcut("q")
                } label: { Image(systemName: "ellipsis").frame(width: 16, height: 20) }
                    .menuStyle(.borderlessButton).menuIndicator(.hidden).fixedSize()
                    .help(s.text("action.more")).accessibilityLabel(s.text("action.more"))
            }
        }.padding(16)
    }

    private func recentTask(_ row: BreakdownRow, dashboard: Dashboard) -> some View {
        let s = settings.strings
        return Button {
            model.openTask(row.id)
            openWindow(id: "dashboard")
            NSApp.activate(ignoringOtherApps: true)
        } label: {
            HStack(alignment: .firstTextBaseline, spacing: 10) {
                VStack(alignment: .leading, spacing: 4) {
                    Text(s.label(row, kind: .session)).font(.subheadline.weight(.medium)).lineLimit(1)
                    HStack(spacing: 5) {
                        if let harness = row.provider { Text(harness.label) }
                        if let date = row.latestDate { Text(s.relative(date)) }
                    }.font(.caption2).foregroundStyle(.secondary)
                }
                Spacer(minLength: 4)
                Text(s.cost(dashboard.familySummary(row), compact: true))
                    .font(.subheadline).monospacedDigit().help(s.text("usage.familyCost"))
                Image(systemName: "chevron.right").font(.caption2).foregroundStyle(.tertiary)
            }.padding(.vertical, 4).contentShape(Rectangle())
        }.buttonStyle(.plain)
    }
}
