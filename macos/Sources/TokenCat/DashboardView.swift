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
    @State private var modelSearch = ""
    @State private var projectSearch = ""
    @State private var taskSearch = ""
    @State private var modelSort: UsageSort = .cost
    @State private var projectSort: UsageSort = .cost
    @State private var taskSort: UsageSort = .recent
    @State private var expandedTasks: Set<String> = []
    @State private var pendingTaskReveal: String?

    var body: some View {
        let s = settings.strings
        NavigationSplitView {
            List(DashboardPage.allCases, selection: $page) { item in
                Label(s.text(item.key), systemImage: item.symbol).tag(item)
                    .padding(.vertical, 4)
            }
            .navigationSplitViewColumnWidth(min: 170, ideal: 190, max: 230)
            .safeAreaInset(edge: .top) {
                HStack(spacing: 10) {
                    Image(systemName: "cat.fill").font(.title2).foregroundStyle(TokenCatTheme.accent)
                    VStack(alignment: .leading, spacing: 3) {
                        Text("TokenCat").font(.headline)
                        Text(s.text("app.localOnly")).font(.caption2).foregroundStyle(.secondary)
                    }
                    Spacer()
                }.padding(16)
            }
            .safeAreaInset(edge: .bottom) {
                VStack(alignment: .leading, spacing: 14) {
                    StatusFooter(dashboard: model.dashboard)
                    SettingsLink { Label(s.text("settings.title"), systemImage: "gearshape") }
                        .buttonStyle(.plain).font(.caption)
                }.padding(16)
            }
        } detail: {
            Group {
                if let dashboard = model.dashboard {
                    VStack(spacing: 0) {
                        if model.error != nil {
                            HStack {
                                Label(s.text("status.retained"), systemImage: "exclamationmark.circle")
                                Spacer()
                                Button(s.text("action.retry")) { model.requestRefresh() }
                            }.font(.caption).foregroundStyle(.orange).padding(12)
                                .background(Color.orange.opacity(0.08))
                        }
                        switch page ?? .overview {
                        case .overview: overview(dashboard)
                        case .models: breakdown(dashboard.models, kind: .model, search: $modelSearch, sort: $modelSort)
                        case .projects: breakdown(dashboard.projects, kind: .project, search: $projectSearch, sort: $projectSort)
                        case .sessions: tasks(dashboard)
                        }
                    }
                } else { LoadingOrEmpty() }
            }
            .navigationTitle(s.text((page ?? .overview).key))
            .background(Color(nsColor: .windowBackgroundColor))
            .toolbar {
                ToolbarItem(placement: .principal) {
                    Picker(s.text("period.title"), selection: $model.window) {
                        ForEach(TimeWindow.allCases) { Text(s.text($0.localizationKey)).tag($0) }
                    }.pickerStyle(.segmented).frame(width: 250)
                }
                ToolbarItem {
                    Button { model.requestRefresh() } label: {
                        Image(systemName: "arrow.clockwise")
                    }.help(s.text("action.refresh")).disabled(model.refreshing)
                        .accessibilityLabel(s.text("accessibility.refresh"))
                        .keyboardShortcut("r", modifiers: .command)
                }
            }
        }
        .frame(minWidth: 800, minHeight: 560)
        .onReceive(model.$selectedTaskId) { id in
            if let id {
                page = .sessions
                pendingTaskReveal = model.dashboard == nil ? id : nil
                revealTask(id, in: model.dashboard)
            } else {
                pendingTaskReveal = nil
            }
        }
        .onReceive(model.$dashboard) { dashboard in
            guard let dashboard else {
                pendingTaskReveal = model.selectedTaskId
                return
            }
            if let id = pendingTaskReveal {
                revealTask(id, in: dashboard)
                pendingTaskReveal = nil
            }
        }
        .onAppear { if model.selectedTaskId != nil { page = .sessions } }
    }

    private func overview(_ dashboard: Dashboard) -> some View {
        let s = settings.strings
        return GeometryReader { geometry in
            let wide = geometry.size.width >= 760
            ScrollView {
                VStack(alignment: .leading, spacing: 20) {
                    HStack(alignment: .firstTextBaseline) {
                        Label(s.text(model.window.localizationKey), systemImage: "calendar")
                            .font(.subheadline.weight(.medium))
                        Spacer()
                        Text(settings.timezone.isEmpty ? TimeZone.autoupdatingCurrent.identifier : settings.timezone)
                            .font(.caption2).foregroundStyle(.secondary).help(s.text("settings.timezone"))
                    }
                    if wide {
                        HStack(alignment: .top, spacing: 16) {
                            hero(dashboard).frame(maxWidth: .infinity)
                            providers(dashboard).frame(width: 280)
                        }
                    } else {
                        hero(dashboard)
                        providers(dashboard)
                    }
                    SurfaceCard {
                        HStack(spacing: 18) {
                            metric("cache.ratio", value: dashboard.summary.cacheReadRatio.map(s.percent) ?? s.text("usage.notAvailable"), symbol: "arrow.2.circlepath", detail: s.text("cache.explanation"))
                            Divider()
                            metric("usage.sessions", value: s.count(UInt64(dashboard.rootSessions.count)), symbol: "rectangle.stack")
                            Divider()
                            metric("usage.models", value: s.count(UInt64(dashboard.models.count)), symbol: "cpu")
                        }.fixedSize(horizontal: false, vertical: true)
                    }
                    SurfaceCard {
                        UsageChart(buckets: dashboard.timeline, window: model.window)
                    }
                    if dashboard.summary.eventCount == 0 {
                        ContentUnavailableView {
                            Label(s.text("usage.noEvents"), systemImage: "cat")
                        } description: {
                            Text(s.text("usage.emptyDescription"))
                        } actions: {
                            SettingsLink { Text(s.text("settings.sources")) }
                        }.frame(maxWidth: .infinity)
                    } else {
                        if wide {
                            HStack(alignment: .top, spacing: 16) {
                                ranking(dashboard.models, page: .models, kind: .model)
                                ranking(dashboard.projects, page: .projects, kind: .project)
                            }
                        } else {
                            ranking(dashboard.models, page: .models, kind: .model)
                            ranking(dashboard.projects, page: .projects, kind: .project)
                        }
                        SurfaceCard {
                            VStack(alignment: .leading, spacing: 14) {
                                sectionLink("usage.recentTasks", destination: .sessions)
                                ForEach(dashboard.rootSessions.prefix(5)) { row in
                                    Button { selectTask(row.id) } label: {
                                        taskRow(row, dashboard: dashboard).padding(.vertical, 4).contentShape(Rectangle())
                                    }.buttonStyle(.plain)
                                    if row.id != dashboard.rootSessions.prefix(5).last?.id { Divider() }
                                }
                            }
                        }
                    }
                    catalog(dashboard)
                }.padding(24).frame(maxWidth: 1200).frame(maxWidth: .infinity)
            }
        }
    }

    private func hero(_ dashboard: Dashboard) -> some View {
        let s = settings.strings
        return SurfaceCard {
            VStack(alignment: .leading, spacing: 14) {
                TokenUsageHero(summary: dashboard.summary)
                if let coverage = dashboard.summary.cost.coverage {
                    Text(s.format("cost.coverage", s.percent(coverage)))
                        .font(.caption2).foregroundStyle(.secondary)
                }
            }.frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    private func providers(_ dashboard: Dashboard) -> some View {
        SurfaceCard {
            VStack(alignment: .leading, spacing: 16) {
                SectionHeading(title: settings.strings.text("usage.harnesses"))
                ForEach(dashboard.providers) { HarnessRow(row: $0) }
                if dashboard.providers.isEmpty {
                    Text(settings.strings.text("usage.waitingSources")).font(.caption).foregroundStyle(.secondary)
                }
            }.frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    private func metric(_ key: String, value: String, symbol: String, detail: String? = nil) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Label(settings.strings.text(key), systemImage: symbol)
                .font(.caption).foregroundStyle(.secondary).lineLimit(1)
            Text(value).font(.system(.title2, design: .rounded, weight: .semibold))
                .monospacedDigit().lineLimit(1).minimumScaleFactor(0.7)
        }.frame(maxWidth: .infinity, alignment: .leading)
            .help(detail ?? value)
    }

    private func sectionLink(_ key: String, destination: DashboardPage) -> some View {
        HStack {
            SectionHeading(title: settings.strings.text(key))
            Button { page = destination } label: {
                Label(settings.strings.text("action.viewAll"), systemImage: "arrow.right")
                    .font(.caption).fixedSize()
            }.buttonStyle(.plain).foregroundStyle(TokenCatTheme.accent)
        }
    }

    private func ranking(_ rows: [BreakdownRow], page: DashboardPage, kind: BreakdownKind) -> some View {
        let s = settings.strings
        let sorted = s.matchingRows(rows, query: "", kind: kind, sort: .cost)
        return SurfaceCard {
            VStack(alignment: .leading, spacing: 16) {
                sectionLink(page.key, destination: page)
                ForEach(sorted.prefix(4)) { row in
                    VStack(spacing: 7) {
                        HStack(spacing: 10) {
                            Text(s.label(row, kind: kind)).lineLimit(1).help(s.label(row, kind: kind))
                            Spacer(minLength: 4)
                            Text(s.cost(row.summary.cost, compact: true)).monospacedDigit().fixedSize()
                        }.font(.subheadline)
                        if let top = sorted.first, top.summary.cost.maxUsd > 0 {
                            ProgressView(value: row.summary.cost.maxUsd, total: top.summary.cost.maxUsd)
                                .tint(row.provider?.tint ?? TokenCatTheme.accent).accessibilityHidden(true)
                        }
                    }
                }
            }.frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    private func breakdown(_ rows: [BreakdownRow], kind: BreakdownKind, search: Binding<String>, sort: Binding<UsageSort>) -> some View {
        let s = settings.strings
        let filtered = s.matchingRows(rows, query: search.wrappedValue, kind: kind, sort: sort.wrappedValue)
        return VStack(spacing: 0) {
            listControls(count: filtered.count, sort: sort)
            if kind == .project && !settings.showPaths {
                HStack(spacing: 8) {
                    Label(s.text("usage.projectDescription"), systemImage: "eye.slash")
                    Spacer()
                    SettingsLink { Text(s.text("action.settings")) }
                }.font(.caption).foregroundStyle(.secondary).padding(.horizontal, 18).padding(.bottom, 12)
            }
            if filtered.isEmpty {
                emptyResults(search: search)
            } else {
                List(filtered) { row in
                    DisclosureGroup {
                        CostBreakdown(summary: row.summary).padding(.vertical, 14).frame(maxWidth: 540, alignment: .leading)
                    } label: {
                        HStack(spacing: 16) {
                            VStack(alignment: .leading, spacing: 5) {
                                Text(s.label(row, kind: kind)).font(.subheadline.weight(.medium)).lineLimit(1)
                                    .help(s.label(row, kind: kind))
                                Text([row.provider?.label, s.eventCount(row.summary.eventCount)].compactMap { $0 }.joined(separator: " · "))
                                    .font(.caption).foregroundStyle(.secondary)
                            }
                            Spacer(minLength: 12)
                            VStack(alignment: .trailing, spacing: 5) {
                                Text(s.cost(row.summary.cost, compact: true)).font(.subheadline.weight(.medium))
                                Text(s.compactCount(row.summary.cost.totalTokens) + " " + s.text("tokens.title"))
                                    .font(.caption).foregroundStyle(.secondary)
                            }.monospacedDigit()
                        }.padding(.vertical, 10)
                    }
                }.listStyle(.inset)
            }
        }.searchable(text: search, prompt: s.text(kind == .model ? "usage.searchModels" : "usage.searchProjects"))
    }

    private func listControls(count: Int, sort: Binding<UsageSort>) -> some View {
        HStack {
            Text(settings.strings.format("usage.resultCount", count)).font(.caption).foregroundStyle(.secondary)
            Spacer()
            Picker(settings.strings.text("sort.title"), selection: sort) {
                ForEach(UsageSort.allCases) { Text(settings.strings.text($0.localizationKey)).tag($0) }
            }.fixedSize().controlSize(.small)
        }.padding(16)
    }

    private func emptyResults(search: Binding<String>) -> some View {
        let s = settings.strings
        let searching = !search.wrappedValue.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        return ContentUnavailableView {
            Label(s.text(searching ? "usage.noResults" : "usage.noEvents"), systemImage: searching ? "magnifyingglass" : "tray")
        } description: {
            Text(s.text(searching ? "usage.searchHint" : "usage.emptyDescription"))
        } actions: {
            if searching { Button(s.text("action.clearSearch")) { search.wrappedValue = "" } }
        }.frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    private func tasks(_ dashboard: Dashboard) -> some View {
        let s = settings.strings
        let searching = !taskSearch.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        let rows = searching ? dashboard.matchingTasks(query: taskSearch, localizer: s, sort: taskSort)
            : dashboard.sortedTasks(dashboard.rootSessions, by: taskSort)
        return HSplitView {
            VStack(spacing: 0) {
                listControls(count: rows.count, sort: $taskSort)
                if rows.isEmpty { emptyResults(search: $taskSearch) }
                else {
                    List(selection: $model.selectedTaskId) {
                        ForEach(rows) { row in
                            if searching { taskRow(row, dashboard: dashboard).padding(.vertical, 6).tag(row.id) }
                            else { taskTree(row, dashboard: dashboard, ancestors: []) }
                        }
                    }.listStyle(.inset)
                }
            }.frame(minWidth: 250, idealWidth: 340, maxWidth: 430)
                .searchable(text: $taskSearch, prompt: s.text("usage.searchTasks"))
            ScrollView {
                if let row = model.selectedTask {
                    taskDetail(row, dashboard: dashboard)
                } else {
                    ContentUnavailableView {
                        Label(s.text(model.selectedTaskId == nil ? "usage.noSelection" : "usage.selectionOutsidePeriod"), systemImage: "rectangle.stack")
                    } actions: {
                        if model.selectedTaskId != nil {
                            Button(s.text("action.clearSelection")) { model.selectedTaskId = nil }
                        }
                    }.padding(.top, 64)
                }
            }.frame(minWidth: 290, maxWidth: .infinity, maxHeight: .infinity)
        }
    }

    private func taskDetail(_ row: BreakdownRow, dashboard: Dashboard) -> some View {
        let s = settings.strings
        let children = dashboard.children(of: row.id).filter { $0.id != row.id }
        return VStack(alignment: .leading, spacing: 20) {
            VStack(alignment: .leading, spacing: 10) {
                Text(s.label(row, kind: .session)).font(.title2.weight(.semibold)).textSelection(.enabled)
                if let harness = row.provider { Label(harness.label, systemImage: harness.symbol).font(.subheadline).foregroundStyle(harness.tint) }
                if let date = row.latestDate { Text(s.text("usage.lastEvent") + " " + s.relative(date)).font(.caption).foregroundStyle(.secondary) }
                if let parent = dashboard.sessions.first(where: { $0.id == row.parentId && $0.id != row.id }) {
                    Button { selectTask(parent.id) } label: {
                        Label(s.text("usage.parentTask"), systemImage: "arrow.turn.up.left")
                    }.buttonStyle(.plain).font(.caption).foregroundStyle(TokenCatTheme.accent)
                }
            }
            SurfaceCard { CostHero(summary: row.summary, compact: true, titleKey: "usage.directCost") }
            if !children.isEmpty {
                SurfaceCard {
                    VStack(alignment: .leading, spacing: 16) {
                        HStack(alignment: .firstTextBaseline) {
                            Text(s.text("usage.familyCost")).font(.subheadline)
                            Spacer()
                            Text(s.cost(dashboard.familySummary(row))).font(.headline).monospacedDigit()
                        }
                        Divider()
                        SectionHeading(title: s.text("usage.subtasks"))
                        ForEach(children) { child in
                            Button { selectTask(child.id) } label: { taskRow(child, dashboard: dashboard) }.buttonStyle(.plain)
                        }
                    }
                }
            }
            if let context = dashboard.states.filter({ $0.kind == "context" && "\($0.provider.rawValue):\($0.sessionId)" == row.id }).max(by: { $0.timestampMs < $1.timestampMs }) {
                SurfaceCard { ContextObservationView(observation: context) }
            }
            SurfaceCard { CostBreakdown(summary: row.summary) }
        }.padding(20).frame(maxWidth: .infinity, alignment: .leading)
    }

    private func taskTree(_ row: BreakdownRow, dashboard: Dashboard, ancestors: Set<String>) -> AnyView {
        let nextAncestors = ancestors.union([row.id])
        let children = dashboard.sortedTasks(dashboard.children(of: row.id).filter { !nextAncestors.contains($0.id) }, by: taskSort)
        if children.isEmpty {
            return AnyView(taskRow(row, dashboard: dashboard).padding(.vertical, 6).tag(row.id))
        }
        return AnyView(DisclosureGroup(isExpanded: Binding(
            get: { expandedTasks.contains(row.id) },
            set: { if $0 { expandedTasks.insert(row.id) } else { expandedTasks.remove(row.id) } }
        )) {
            ForEach(children) { child in taskTree(child, dashboard: dashboard, ancestors: nextAncestors) }
        } label: {
            taskRow(row, dashboard: dashboard).padding(.vertical, 6)
        }.tag(row.id))
    }

    private func taskRow(_ row: BreakdownRow, dashboard: Dashboard) -> some View {
        let s = settings.strings
        let family = dashboard.taskFamily(row)
        let cost = dashboard.familySummary(row)
        return HStack(spacing: 10) {
            VStack(alignment: .leading, spacing: 5) {
                Text(s.label(row, kind: .session)).font(.subheadline.weight(.medium)).lineLimit(1).help(s.label(row, kind: .session))
                HStack(spacing: 5) {
                    if let provider = row.provider { Text(provider.label) }
                    if row.parentId != nil { Image(systemName: "arrow.turn.down.right").help(s.text("usage.subtasks")) }
                    if let date = family.compactMap(\.latestDate).max() { Text(s.relative(date)) }
                }.font(.caption2).foregroundStyle(.secondary).lineLimit(1)
            }
            Spacer(minLength: 4)
            VStack(alignment: .trailing, spacing: 5) {
                Text(s.cost(cost, compact: true)).font(.subheadline).monospacedDigit().lineLimit(1)
                if family.count > 1 {
                    Text(s.text("usage.includesSubtasks")).font(.caption2).foregroundStyle(.secondary)
                }
            }.help(s.text(family.count > 1 ? "usage.familyCost" : "usage.directCost"))
        }.contentShape(Rectangle())
    }

    private func selectTask(_ id: String) {
        taskSearch = ""
        model.selectedTaskId = id
        page = .sessions
    }

    private func revealTask(_ id: String, in dashboard: Dashboard?) {
        guard let dashboard else { return }
        if !taskSearch.isEmpty && !dashboard.matchingTasks(query: taskSearch, localizer: settings.strings, sort: taskSort).contains(where: { $0.id == id }) {
            taskSearch = ""
        }
        var visited: Set<String> = [id]
        var current = dashboard.sessions.first { $0.id == id }
        while let parentId = current?.parentId, visited.insert(parentId).inserted {
            expandedTasks.insert(parentId)
            current = dashboard.sessions.first { $0.id == parentId }
        }
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
