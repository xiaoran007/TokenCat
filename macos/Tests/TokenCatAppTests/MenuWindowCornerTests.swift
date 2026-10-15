import AppKit
import XCTest
@testable import TokenCat

@MainActor
final class MenuWindowCornerTests: XCTestCase {
    func testClipsNativeFrameIncludingBackgroundOutsideTheContentView() throws {
        _ = NSApplication.shared
        let panel = NSPanel(contentRect: NSRect(x: 0, y: 0, width: 390, height: 700),
                            styleMask: [.borderless], backing: .buffered, defer: false)
        panel.isReleasedWhenClosed = false
        defer { panel.close() }
        let content = NSView(frame: NSRect(x: 0, y: 0, width: 390, height: 700))
        panel.contentView = content
        let frame = try XCTUnwrap(content.superview)
        let nativeBackground = NSVisualEffectView(frame: frame.bounds)
        frame.addSubview(nativeBackground, positioned: .below, relativeTo: content)

        content.addSubview(MenuWindowCornerView())

        XCTAssertFalse(panel.isOpaque)
        XCTAssertEqual(panel.backgroundColor, .clear)
        let layer = try XCTUnwrap(frame.layer)
        XCTAssertEqual(layer.cornerRadius, 24)
        XCTAssertEqual(layer.cornerCurve, .continuous)
        XCTAssertTrue(layer.masksToBounds)
        XCTAssertTrue(nativeBackground.superview === frame, "The native material must be inside the rounded frame.")

        panel.setContentSize(NSSize(width: 390, height: 560))
        frame.layoutSubtreeIfNeeded()
        XCTAssertEqual(layer.cornerRadius, 24)
        XCTAssertTrue(layer.masksToBounds)
    }

    func testDetachedProbeDoesNotModifyUnrelatedWindows() {
        _ = NSApplication.shared
        let unrelated = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 500, height: 500),
                                 styleMask: [.titled], backing: .buffered, defer: false)
        unrelated.isReleasedWhenClosed = false
        defer { unrelated.close() }
        let opaque = unrelated.isOpaque
        let background = unrelated.backgroundColor

        let detached = MenuWindowCornerView()
        detached.viewDidMoveToWindow()

        XCTAssertEqual(unrelated.isOpaque, opaque)
        XCTAssertEqual(unrelated.backgroundColor, background)
    }
}
