import AppKit
import SwiftUI
import XCTest
@testable import TokenCat
@testable import TokenCatKit

@MainActor
final class MenuPanelLayoutTests: XCTestCase {
    func testLoadingMenuKeepsContentWhenHostFitsItsSize() async throws {
        try await withMenu(state: .loading) { host in
            try assertMinimumViewport(host)
            try exportPreviewIfRequested(host, name: "loading")
        }
    }

    func testLoadingMenuKeepsContentAtNormalWindowHeight() async throws {
        try await withMenu(state: .loading) { host in
            host.setFrameSize(NSSize(width: 390, height: 700))
            host.layoutSubtreeIfNeeded()
            try assertVisibleViewport(host)
        }
    }

    func testLoadedMenuKeepsUsageVisibleInBothLanguagesAndAppearances() async throws {
        for language in [AppLanguage.english, .simplifiedChinese] {
            for dark in [false, true] {
                try await withMenu(state: .loaded, language: language, dark: dark) { host in
                    try assertMinimumViewport(host)
                    try exportPreviewIfRequested(host, name: "loaded-\(language.rawValue)-\(dark ? "dark" : "light")")
                }
            }
        }
    }

    func testEmptyMenuKeepsItsZeroUsageVisible() async throws {
        try await withMenu(state: .empty) { host in
            try assertMinimumViewport(host)
            try exportPreviewIfRequested(host, name: "empty")
        }
    }

    func testFailedRefreshKeepsItsErrorVisible() async throws {
        try await withMenu(state: .failed) { host in
            try assertMinimumViewport(host)
            try exportPreviewIfRequested(host, name: "error")
        }
    }

    private enum MenuState { case loading, loaded, empty, failed }

    private func withMenu(state: MenuState, language: AppLanguage = .english, dark: Bool = false,
                          _ body: (NSHostingView<AnyView>) throws -> Void) async throws {
        _ = NSApplication.shared
        let suite = "TokenCat.MenuPanelLayoutTests.\(UUID().uuidString)"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        let settings = AppSettings(defaults: defaults)
        settings.language = language
        settings.home = NSTemporaryDirectory()
        settings.timezone = "America/New_York"
        let result: Result<Dashboard, CoreFailure> = state == .failed
            ? .failure(CoreFailure(message: "Fixture collection failed"))
            : .success(MenuFixtures.dashboard(empty: state == .empty))
        let model = AppModel(settings: settings, worker: FixtureUsageLoader(result: result))
        let settingsWindow = SettingsWindowController(settings: settings, model: model)
        if state != .loading {
            await model.refresh()
            if state == .failed { XCTAssertNotNil(model.error) }
            else {
                XCTAssertNotNil(model.today)
                XCTAssertNotNil(model.dashboard)
            }
        }
        let host = NSHostingView(rootView: AnyView(MenuPanel()
            .environmentObject(model)
            .environmentObject(settings)
            .environmentObject(settingsWindow)
            .environment(\.locale, language.locale)
            .preferredColorScheme(dark ? .dark : .light)))
        host.appearance = NSAppearance(named: dark ? .darkAqua : .aqua)
        try body(host)
    }

    private func assertMinimumViewport(_ host: NSHostingView<AnyView>, file: StaticString = #filePath, line: UInt = #line) throws {
        // MenuBarExtra can propose the smallest supported height while fitting its window.
        // Measure the actual SwiftUI hierarchy, then lay out the native scroll view at that size.
        let controller = NSHostingController(rootView: host.rootView)
        let minimum = controller.sizeThatFits(in: NSSize(width: 390, height: 0))
        host.setFrameSize(minimum)
        host.layoutSubtreeIfNeeded()
        try assertVisibleViewport(host, file: file, line: line)
    }

    private func assertVisibleViewport(_ host: NSHostingView<AnyView>, file: StaticString = #filePath, line: UInt = #line) throws {
        let scroll = try XCTUnwrap(descendants(of: host).compactMap { $0 as? NSScrollView }.first, file: file, line: line)
        let viewport = scroll.contentView.convert(scroll.contentView.bounds, to: host)
        XCTAssertGreaterThanOrEqual(viewport.intersection(host.bounds).height, 140,
                                   "The menu must keep its content visible when its host fits the window.", file: file, line: line)
    }

    private func descendants(of view: NSView) -> [NSView] {
        view.subviews.flatMap { [$0] + descendants(of: $0) }
    }

    private func exportPreviewIfRequested(_ view: NSView, name: String) throws {
        guard let directory = ProcessInfo.processInfo.environment["TOKENCAT_MENU_PREVIEW_DIRECTORY"] else { return }
        let destination = URL(fileURLWithPath: directory, isDirectory: true)
        try FileManager.default.createDirectory(at: destination, withIntermediateDirectories: true)
        let bitmap = try XCTUnwrap(view.bitmapImageRepForCachingDisplay(in: view.bounds))
        view.cacheDisplay(in: view.bounds, to: bitmap)
        let png = try XCTUnwrap(bitmap.representation(using: .png, properties: [:]))
        try png.write(to: destination.appendingPathComponent("menu-\(name).png"))
    }
}
