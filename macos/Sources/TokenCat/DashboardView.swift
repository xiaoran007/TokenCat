import AppKit
import SwiftUI
import TokenCatKit

private enum DashboardPage: String, CaseIterable, Identifiable {
    case overview, models, projects, sessions
    var id: Self { self }
    var symbol: String {
        switch self { case .overview: return "chart.bar.xaxis"; case .models: return "cpu"; case .projects: return "folder"; case .sessions: return "rectangle.stack" }
    }
    var key: String { "usage.\(rawValue)" }
}

struct DashboardView: View {
    @EnvironmentObject private var model: AppModel
    @EnvironmentObject private var settings: AppSettings
    @State private var page: DashboardPage? = .overview
    @State private var search = ""
    var body: some View {
        let s = settings.strings
        NavigationSplitView {
            List(DashboardPage.allCases, selection: $page) { item in
                Label(s.text(item.key), systemImage: item.symbol).tag(item)
            }
            .navigationSplitViewColumnWidth(min: 170, ideal: 190, max: 250)
            .safeAreaInset(edge: .bottom) {
                VStack(alignment: .leading, spacing: 12) {
                    StatusFooter(dashboard: model.dashboard)
                    SettingsLink { Label(s.text("settings.title"), systemImage: "gearshape") }.buttonStyle(.plain).font(.caption)
                }.padding(16)
            }
        } detail: {
            Group {
                if let dashboard = model.dashboard {
                    switch page ?? .overview {
                    case .overview: overview(dashboard)
                    case .models: breakdown(dashboard.models, title: s.text("usage.models"), kind: .model)
                    case .projects: breakdown(dashboard.projects, title: s.text("usage.projects"), kind: .project)
                    case .sessions: tasks(dashboard)
                    }
                } else { LoadingOrEmpty() }
            }
            .navigationTitle(s.text((page ?? .overview).key))
            .toolbar {
                ToolbarItem(placement: .principal) {
                    Picker(s.text("chart.time"), selection: $model.window) {
                        ForEach(TimeWindow.allCases) { Text(s.text($0.localizationKey)).tag($0) }
                    }.pickerStyle(.segmented).frame(width: 260)
                }
                ToolbarItem {
                    Button { model.requestRefresh() } label: { Image(systemName: "arrow.clockwise") }
                        .help(s.text("action.refresh")).disabled(model.refreshing)
                }
            }
        }
        .frame(minWidth: 800, minHeight: 560)
        .onReceive(model.$selectedTaskId) { id in if id != nil { page = .sessions } }
        .onAppear { if model.selectedTaskId != nil { page = .sessions } }
    }

    private func overview(_ dashboard: Dashboard) -> some View {
        let s = settings.strings
        return ScrollView {
            VStack(alignment: .leading, spacing: 28) {
                if model.error != nil {
                    Label(s.text("status.retained"), systemImage: "exclamationmark.circle").font(.caption).foregroundStyle(.orange)
                }
                HStack(alignment: .top, spacing: 36) {
                    CostHero(summary: dashboard.summary, compact: false).frame(maxWidth: .infinity, alignment: .leading)
                    VStack(alignment: .leading, spacing: 14) { ForEach(dashboard.providers) { HarnessRow(row: $0) } }
                        .frame(width: 270)
                }
                GroupBox {
                    VStack(alignment: .leading, spacing: 16) {
                        SectionHeading(title: s.text("usage.trend"))
                        UsageChart(buckets: dashboard.timeline)
                    }.padding(12)
                }
                if dashboard.summary.eventCount == 0 {
                    ContentUnavailableView(s.text("usage.noEvents"), systemImage: "chart.xyaxis.line", description: Text(s.text("usage.emptyDescription")))
                } else {
                    HStack(alignment: .top, spacing: 20) {
                        ranking(dashboard.models, title: s.text("usage.models"), kind: .model)
                        ranking(dashboard.projects, title: s.text("usage.projects"), kind: .project)
                    }
                    SectionHeading(title: s.text("usage.recentTasks"))
                    VStack(spacing: 0) {
                        ForEach(dashboard.rootSessions.prefix(5)) { row in
                            Button { model.selectedTaskId = row.id; page = .sessions } label: {
                                taskRow(row).padding(.vertical, 12).contentShape(Rectangle())
                            }.buttonStyle(.plain)
                            Divider()
                        }
                    }
                }
                catalog(dashboard)
            }.padding(28)
        }
    }

    private func ranking(_ rows: [BreakdownRow], title: String, kind: BreakdownKind) -> some View {
        let s = settings.strings
        let sorted = rows.sorted { $0.summary.cost.maxUsd > $1.summary.cost.maxUsd }
        return GroupBox {
            VStack(alignment: .leading, spacing: 14) {
                SectionHeading(title: title)
                ForEach(sorted.prefix(4)) { row in
                    VStack(spacing: 5) {
                        HStack {
                            Text(s.label(row, kind: kind)).lineLimit(1)
                            Spacer()
                            Text(s.cost(row.summary.cost, compact: true)).monospacedDigit()
                        }.font(.subheadline)
                        if let top = sorted.first, top.summary.cost.maxUsd > 0 {
                            ProgressView(value: row.summary.cost.maxUsd, total: top.summary.cost.maxUsd).tint(row.provider?.tint ?? .accentColor)
                                .accessibilityHidden(true)
                        }
                    }
                }
            }.padding(12).frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    private func breakdown(_ rows: [BreakdownRow], title: String, kind: BreakdownKind) -> some View {
        let s = settings.strings
        let filtered = rows.filter { search.isEmpty || s.label($0, kind: kind).localizedCaseInsensitiveContains(search) }
            .sorted { $0.summary.cost.maxUsd > $1.summary.cost.maxUsd }
        return List {
            ForEach(filtered) { row in
                DisclosureGroup {
                    CostBreakdown(summary: row.summary).padding(.vertical, 12).frame(maxWidth: 500, alignment: .leading)
                } label: { taskRow(row, kind: kind).padding(.vertical, 6) }
            }
        }.listStyle(.inset).searchable(text: $search, prompt: title)
    }

    private func tasks(_ dashboard: Dashboard) -> some View {
        let s = settings.strings
        return HSplitView {
            List(selection: $model.selectedTaskId) {
                ForEach(dashboard.rootSessions.filter { search.isEmpty || s.label($0, kind: .session).localizedCaseInsensitiveContains(search) }) { row in
                    taskTree(row, dashboard: dashboard, ancestors: [])
                }
            }.listStyle(.inset).frame(minWidth: 260, idealWidth: 330, maxWidth: 400)
                .searchable(text: $search, prompt: s.text("usage.sessions"))
            ScrollView {
                if let row = model.selectedTask {
                    VStack(alignment: .leading, spacing: 24) {
                        VStack(alignment: .leading, spacing: 8) {
                            Text(s.label(row, kind: .session)).font(.title2.weight(.semibold)).textSelection(.enabled)
                            if let harness = row.provider { Label(harness.label, systemImage: harness.symbol).foregroundStyle(harness.tint) }
                            if let date = row.latestDate { Text(s.text("usage.lastEvent") + " " + s.relative(date)).font(.caption).foregroundStyle(.secondary) }
                        }
                        CostHero(summary: row.summary, compact: true, titleKey: "usage.directCost")
                        if let context = dashboard.states.filter({ $0.kind == "context" && "\($0.provider.rawValue):\($0.sessionId)" == row.id }).max(by: { $0.timestampMs < $1.timestampMs }) {
                            ContextObservationView(observation: context)
                        }
                        let children = dashboard.children(of: row.id).filter { $0.id != row.id }
                        if !children.isEmpty {
                            familyCost(row, dashboard: dashboard)
                            SectionHeading(title: s.text("usage.subtasks"))
                            ForEach(children) { child in
                                Button { model.selectedTaskId = child.id } label: { taskRow(child) }.buttonStyle(.plain)
                            }
                        }
                        Divider()
                        CostBreakdown(summary: row.summary)
                    }.padding(24).frame(maxWidth: .infinity, alignment: .leading)
                } else {
                    ContentUnavailableView(s.text("usage.noSelection"), systemImage: "rectangle.stack").padding(.top, 80)
                }
            }.frame(minWidth: 310, maxWidth: .infinity, maxHeight: .infinity)
        }
    }

    private func taskTree(_ row: BreakdownRow, dashboard: Dashboard, ancestors: Set<String>) -> AnyView {
        let nextAncestors = ancestors.union([row.id])
        let children = dashboard.children(of: row.id).filter { !nextAncestors.contains($0.id) }
        if children.isEmpty {
            return AnyView(taskRow(row).padding(.vertical, 4).tag(row.id))
        }
        return AnyView(DisclosureGroup {
            ForEach(children) { child in taskTree(child, dashboard: dashboard, ancestors: nextAncestors) }
        } label: { taskRow(row).padding(.vertical, 4).tag(row.id) }.tag(row.id))
    }

    private func taskRow(_ row: BreakdownRow, kind: BreakdownKind = .session) -> some View {
        let s = settings.strings
        return HStack(spacing: 12) {
            VStack(alignment: .leading, spacing: 5) {
                Text(s.label(row, kind: kind)).font(.subheadline.weight(.medium)).lineLimit(1)
                HStack(spacing: 6) {
                    if let provider = row.provider { Text(provider.label) }
                    Text(s.eventCount(row.summary.eventCount))
                }.font(.caption).foregroundStyle(.secondary)
            }
            Spacer(minLength: 8)
            Text(s.cost(row.summary.cost, compact: true)).font(.subheadline).monospacedDigit()
        }
    }

    private func familyCost(_ row: BreakdownRow, dashboard: Dashboard) -> some View {
        let s = settings.strings
        let family = dashboard.familySummary(row)
        return HStack {
            Text(s.text("usage.familyCost")).font(.subheadline)
            Spacer()
            Text(s.cost(family)).monospacedDigit()
        }.padding(14).background(.quaternary.opacity(0.4), in: RoundedRectangle(cornerRadius: 10))
    }

    private func catalog(_ dashboard: Dashboard) -> some View {
        let s = settings.strings
        return DisclosureGroup(s.text("cost.catalog")) {
            VStack(alignment: .leading, spacing: 8) {
                LabeledContent(s.text("cost.version"), value: dashboard.catalogId)
                LabeledContent(s.text("cost.retrieved"), value: dashboard.catalogRetrievedAt)
                ForEach(dashboard.catalogSources, id: \.self) { source in
                    if let url = URL(string: source) { Link(source, destination: url) }
                }
            }.font(.caption).foregroundStyle(.secondary).padding(.top, 10)
        }.font(.caption).foregroundStyle(.secondary)
    }
}
