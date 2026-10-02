import AppKit
import SwiftUI
import ServiceManagement
import TokenCatKit

struct SettingsView: View {
    @EnvironmentObject private var settings: AppSettings
    @EnvironmentObject private var model: AppModel
    var body: some View {
        let s = settings.strings
        TabView {
            general.tabItem { Label(s.text("settings.general"), systemImage: "gearshape") }
            sources.tabItem { Label(s.text("settings.sources"), systemImage: "folder") }
            pricing.tabItem { Label(s.text("settings.pricing"), systemImage: "dollarsign.circle") }
        }.padding(16).frame(width: 590, height: 520)
    }
    private var general: some View {
        let s = settings.strings
        return Form {
            Section {
                Picker(s.text("settings.language"), selection: $settings.language) {
                    ForEach(AppLanguage.allCases) { language in
                        Text(language == .system ? s.text(language.nativeName) : language.nativeName).tag(language)
                    }
                }
                Text(s.text("settings.previewLocale")).font(.caption).foregroundStyle(.secondary)
                Picker(s.text("settings.appearance"), selection: $settings.appearance) {
                    ForEach(["system", "light", "dark"], id: \.self) { Text(s.text("appearance.\($0)")).tag($0) }
                }
                Toggle(s.text("settings.menuCost"), isOn: $settings.showMenuCost)
                Toggle(s.text("settings.startLogin"), isOn: Binding(get: { settings.loginEnabled }, set: { settings.setLogin($0) }))
                if SMAppService.mainApp.status == .requiresApproval {
                    Button(s.text("settings.loginApproval")) { SMAppService.openSystemSettingsLoginItems() }.font(.caption)
                }
                if let error = settings.loginError {
                    DisclosureGroup(s.text("settings.loginError")) {
                        Text(error).font(.caption).foregroundStyle(.secondary).textSelection(.enabled)
                    }.font(.caption).foregroundStyle(.red)
                }
            }
            Section {
                Picker(s.text("settings.refresh"), selection: $settings.refreshSeconds) {
                    ForEach([2, 5, 10, 30], id: \.self) { Text(s.format("settings.refreshSeconds", $0)).tag($0) }
                }
                TextField(s.text("settings.timezone"), text: $settings.timezone, prompt: Text(TimeZone.autoupdatingCurrent.identifier))
                if settings.timeZone == nil { Text(s.text("settings.invalidTimezone")).font(.caption).foregroundStyle(.red) }
            }
        }.formStyle(.grouped)
    }
    private var sources: some View {
        let s = settings.strings
        return Form {
            Section {
                HStack {
                    TextField(s.text("settings.home"), text: $settings.home)
                    Button(s.text("action.choose")) { chooseDirectory { settings.home = $0 } }
                }
                Text(s.text("settings.homeExplanation")).font(.caption).foregroundStyle(.secondary)
                if !settings.validHome { Text(s.text("settings.invalidHome")).font(.caption).foregroundStyle(.red) }
                HStack {
                    TextField(s.text("settings.codexRoot"), text: $settings.codexRoot)
                    Button(s.text("action.choose")) { chooseDirectory { settings.codexRoot = $0 } }
                }
                VStack(alignment: .leading, spacing: 5) {
                    Text(s.text("settings.claudeRoots")).font(.subheadline)
                    TextEditor(text: $settings.claudeRoots).font(.system(.caption, design: .monospaced)).frame(height: 56)
                        .overlay(RoundedRectangle(cornerRadius: 5).stroke(.quaternary))
                    Text(s.text("settings.claudeExplanation")).font(.caption).foregroundStyle(.secondary)
                }
            }
            Section(s.text("settings.privacy")) {
                Toggle(s.text("settings.showProjects"), isOn: $settings.showPaths)
                Text(s.text("settings.privacyExplanation")).font(.caption).foregroundStyle(.secondary)
            }
            Section(s.text("settings.storage")) {
                Button(s.text("action.reveal")) { NSWorkspace.shared.activateFileViewerSelecting([settings.databaseURL]) }
                Text(s.text("settings.restartCore")).font(.caption).foregroundStyle(.secondary)
            }
        }.formStyle(.grouped)
    }
    private var pricing: some View {
        let s = settings.strings
        return Form {
            Section(s.text("cost.catalog")) {
                Text(s.text("settings.catalogExplanation")).font(.subheadline).foregroundStyle(.secondary)
                HStack {
                    Text(settings.pricingPath.isEmpty ? s.text("settings.bundled") : settings.pricingPath).font(.caption).lineLimit(2).textSelection(.enabled)
                    Spacer()
                    Button(s.text("action.choose")) {
                        let panel = NSOpenPanel()
                        panel.allowedContentTypes = [.json]
                        panel.canChooseDirectories = false
                        panel.allowsMultipleSelection = false
                        if panel.runModal() == .OK, let url = panel.url { settings.pricingPath = url.path }
                    }
                }
                if !settings.pricingPath.isEmpty { Button(s.text("action.reset")) { settings.pricingPath = "" } }
            }
            if let snapshot = model.dashboard {
                Section {
                    LabeledContent(s.text("cost.version"), value: snapshot.catalogId)
                    LabeledContent(s.text("cost.retrieved"), value: snapshot.catalogRetrievedAt)
                }
                Section(s.text("cost.sources")) {
                    ForEach(snapshot.catalogSources, id: \.self) { source in
                        if let url = URL(string: source) { Link(source, destination: url).font(.caption) }
                    }
                }
            }
        }.formStyle(.grouped)
    }
    private func chooseDirectory(_ selected: (String) -> Void) {
        let panel = NSOpenPanel()
        panel.canChooseFiles = false
        panel.canChooseDirectories = true
        panel.allowsMultipleSelection = false
        if panel.runModal() == .OK, let url = panel.url { selected(url.path) }
    }
}
