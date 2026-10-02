import AppKit
import SwiftUI
import XCTest
@testable import TokenCat

@MainActor
final class MenuPanelLayoutTests: XCTestCase {
    func testLoadingMenuKeepsContentWhenHostFitsItsSize() throws {
        try withMenu { host in
            let controller = NSHostingController(rootView: host.rootView)
            let size = controller.sizeThatFits(in: NSSize(width: 390, height: 0))
            print("MenuPanel minimum size: \(size); fitting size: \(host.fittingSize)")
            host.setFrameSize(size)
            host.layoutSubtreeIfNeeded()

            let scroll = try XCTUnwrap(descendants(of: host).compactMap { $0 as? NSScrollView }.first)
            print("MenuPanel scroll frame: \(scroll.frame); viewport: \(scroll.contentSize)")
            XCTAssertGreaterThan(size.height, 300, "The panel must reserve space for content as well as its header and footer.")
            XCTAssertGreaterThanOrEqual(scroll.contentSize.height, 140, "Loading content must not collapse to a zero-height viewport.")
            try exportPreviewIfRequested(host)
        }
    }

    func testLoadingMenuKeepsContentAtNormalWindowHeight() throws {
        try withMenu { host in
            host.setFrameSize(NSSize(width: 390, height: 700))
            host.layoutSubtreeIfNeeded()

            let scroll = try XCTUnwrap(descendants(of: host).compactMap { $0 as? NSScrollView }.first)
            XCTAssertGreaterThanOrEqual(scroll.contentSize.height, 140)
            XCTAssertLessThanOrEqual(scroll.frame.maxY, host.bounds.height)
        }
    }

    private func withMenu(_ body: (NSHostingView<AnyView>) throws -> Void) throws {
        _ = NSApplication.shared
        let suite = "TokenCat.MenuPanelLayoutTests.\(UUID().uuidString)"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        let settings = AppSettings(defaults: defaults)
        let model = AppModel(settings: settings)
        let host = NSHostingView(rootView: AnyView(MenuPanel()
            .environmentObject(model)
            .environmentObject(settings)))
        try body(host)
    }

    private func descendants(of view: NSView) -> [NSView] {
        view.subviews.flatMap { [$0] + descendants(of: $0) }
    }

    private func exportPreviewIfRequested(_ view: NSView) throws {
        guard let path = ProcessInfo.processInfo.environment["TOKENCAT_MENU_PREVIEW_PATH"] else { return }
        let bitmap = try XCTUnwrap(view.bitmapImageRepForCachingDisplay(in: view.bounds))
        view.cacheDisplay(in: view.bounds, to: bitmap)
        let png = try XCTUnwrap(bitmap.representation(using: .png, properties: [:]))
        try png.write(to: URL(fileURLWithPath: path))
    }
}
