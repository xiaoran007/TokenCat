import AppKit
import SwiftUI
import XCTest
@testable import TokenCat

@MainActor
final class MenuStyleTransitionTests: XCTestCase {
    func testRepeatedPresetAndAppearanceChangesKeepTheSameContent() async throws {
        _ = NSApplication.shared
        let suite = "TokenCat.MenuStyleTransitionTests.\(UUID().uuidString)"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        let settings = AppSettings(defaults: defaults)
        let recorder = ContentRecorder()
        let host = NSHostingView(rootView: TransitionContent(settings: settings, recorder: recorder))
        let panel = NSPanel(contentRect: NSRect(x: 0, y: 0, width: 390, height: 250),
                            styleMask: [.borderless], backing: .buffered, defer: false)
        panel.isReleasedWhenClosed = false
        panel.contentView = host
        defer { panel.close() }
        host.setFrameSize(NSSize(width: 390, height: 250))
        host.layoutSubtreeIfNeeded()
        try await Task.sleep(for: .milliseconds(40))
        XCTAssertEqual(recorder.createdViews.count, 1)

        for _ in 0..<3 {
            for appearance in ["light", "dark", "system"] {
                for style in MenuPanelStyle.allCases {
                    settings.appearance = appearance
                    settings.menuStyle = style
                    host.layoutSubtreeIfNeeded()
                    try await Task.sleep(for: .milliseconds(40))
                    XCTAssertEqual(recorder.createdViews.count, 1,
                                   "Changing \(appearance)/\(style) must not recreate the menu's stateful content.")
                }
            }
        }
    }
}

@MainActor
private final class ContentRecorder {
    var createdViews: [NSView] = []
}

private struct TransitionContent: View {
    @ObservedObject var settings: AppSettings
    let recorder: ContentRecorder

    var body: some View {
        MenuModuleContainer {
            MenuSection { ContentIdentityProbe(recorder: recorder).frame(width: 100, height: 100) }
        }
        .environmentObject(settings)
        .preferredColorScheme(settings.colorScheme)
    }
}

private struct ContentIdentityProbe: NSViewRepresentable {
    let recorder: ContentRecorder
    func makeNSView(context: Context) -> NSView {
        let view = NSView()
        recorder.createdViews.append(view)
        return view
    }
    func updateNSView(_ nsView: NSView, context: Context) {}
}
