import AppKit
import SwiftUI
import TokenCatKit

struct MenuPanel: View {
    @EnvironmentObject private var model: AppModel
    @EnvironmentObject private var settings: AppSettings
    @Environment(\.openWindow) private var openWindow
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    var body: some View {
        let s = settings.strings
        VStack(alignment: .leading, spacing: 0) {
            HStack {
                Label(s.text("app.name"), systemImage: "cat.fill").font(.subheadline.weight(.semibold))
                Spacer()
                Text(s.text("period.today")).font(.caption).foregroundStyle(.secondary)
                Button { model.requestRefresh() } label: { Image(systemName: "arrow.clockwise") }
                    .buttonStyle(.plain).help(s.text("action.refresh"))
                    .accessibilityLabel(s.text("accessibility.refresh"))
            }.padding(.bottom, 20)
            if let today = model.today {
                CostHero(summary: today.summary, compact: true)
                UsageChart(buckets: today.timeline, compact: true).padding(.top, 16)
                Divider().padding(.vertical, 16)
                VStack(spacing: 12) { ForEach(today.providers) { HarnessRow(row: $0) } }
                if let quota = today.states.filter({ $0.kind == "quota" }).max(by: { $0.timestampMs < $1.timestampMs }) {
                    Divider().padding(.vertical, 16)
                    QuotaObservationView(observation: quota)
                }
                if today.summary.eventCount == 0 {
                    Text(s.text("usage.emptyDescription")).font(.caption).foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true).padding(.top, 16)
                }
                if !today.rootSessions.isEmpty {
                    Divider().padding(.vertical, 16)
                    SectionHeading(title: s.text("usage.recentTasks")).padding(.bottom, 10)
                    VStack(spacing: 12) {
                        ForEach(today.rootSessions.prefix(3)) { row in
                            let family = today.familySummary(row)
                            Button {
                                model.openTask(row.id)
                                openWindow(id: "dashboard")
                                NSApp.activate(ignoringOtherApps: true)
                            } label: {
                                HStack(alignment: .firstTextBaseline, spacing: 10) {
                                    VStack(alignment: .leading, spacing: 4) {
                                        Text(s.label(row, kind: .session)).font(.subheadline).lineLimit(1)
                                        HStack(spacing: 5) {
                                            if let harness = row.provider { Text(harness.label) }
                                            if let date = row.latestDate { Text(s.relative(date)) }
                                        }.font(.caption2).foregroundStyle(.secondary)
                                    }
                                    Spacer(minLength: 4)
                                    Text(s.cost(family, compact: true))
                                        .font(.subheadline).monospacedDigit().help(s.text("usage.familyCost"))
                                    Image(systemName: "chevron.right").font(.caption2).foregroundStyle(.tertiary)
                                }.contentShape(Rectangle())
                            }.buttonStyle(.plain)
                        }
                    }
                }
                Divider().padding(.vertical, 16)
                StatusFooter(dashboard: today)
            } else { LoadingOrEmpty() }
            Divider().padding(.top, 14).padding(.bottom, 10)
            HStack {
                Button(s.text("action.dashboard")) {
                    openWindow(id: "dashboard"); NSApp.activate(ignoringOtherApps: true)
                }.buttonStyle(.plain).font(.subheadline)
                Spacer()
                SettingsLink { Image(systemName: "gearshape") }.buttonStyle(.plain).help(s.text("action.settings"))
                Menu {
                    Button(s.text("action.quit")) { NSApp.terminate(nil) }.keyboardShortcut("q")
                } label: { Image(systemName: "ellipsis.circle") }.menuStyle(.borderlessButton).fixedSize()
            }.foregroundStyle(.secondary)
        }
        .padding(20).frame(width: 390)
        .animation(reduceMotion ? nil : .easeInOut(duration: 0.18), value: model.today?.summary.cost.minUsd)
    }
}
