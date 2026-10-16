import AppKit
import SwiftUI
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
        frame.wantsLayer = true
        let nativeBackground = NSVisualEffectView(frame: frame.bounds)
        frame.addSubview(nativeBackground, positioned: .below, relativeTo: content)
        let contentMaterial = NSVisualEffectView(frame: content.bounds)
        content.addSubview(contentMaterial)

        content.addSubview(MenuWindowCornerView())

        XCTAssertFalse(panel.isOpaque)
        XCTAssertEqual(panel.backgroundColor, .clear)
        let layer = try XCTUnwrap(frame.layer)
        XCTAssertEqual(layer.cornerRadius, 24)
        XCTAssertEqual(layer.cornerCurve, .continuous)
        XCTAssertTrue(layer.masksToBounds)
        XCTAssertTrue(nativeBackground.superview === frame, "The native material must be inside the rounded frame.")
        XCTAssertNotNil(nativeBackground.maskImage)
        XCTAssertNil(contentMaterial.maskImage, "SwiftUI's own materials must not be treated as the window background.")

        panel.setContentSize(NSSize(width: 390, height: 560))
        frame.layoutSubtreeIfNeeded()
        XCTAssertEqual(layer.cornerRadius, 24)
        XCTAssertTrue(layer.masksToBounds)
    }

    func testMaterialMaskMatchesTheFullSizeContentCurveIncludingOuterMargins() throws {
        let bounds = NSRect(x: 0, y: 0, width: 400, height: 710)
        let content = NSRect(x: 5, y: 5, width: 390, height: 700)
        let image = MenuWindowCornerView.materialMask(bounds: bounds, contentRect: content)
        XCTAssertEqual(image.size, bounds.size)
        let bitmap = try XCTUnwrap(NSBitmapImageRep(data: try XCTUnwrap(image.tiffRepresentation)))
        XCTAssertEqual(try XCTUnwrap(bitmap.colorAt(x: 0, y: 0)).alphaComponent, 0, accuracy: 0.01)
        XCTAssertEqual(try XCTUnwrap(bitmap.colorAt(x: 2, y: bitmap.pixelsHigh / 2)).alphaComponent, 0, accuracy: 0.01)
        XCTAssertEqual(try XCTUnwrap(bitmap.colorAt(x: bitmap.pixelsWide / 2, y: bitmap.pixelsHigh / 2)).alphaComponent, 1, accuracy: 0.01)

        // This point was inside a stretched 49x49 mask but outside the real continuous corner.
        let point = CGPoint(x: 21, y: 6.5)
        let shape = RoundedRectangle(cornerRadius: 24, style: .continuous).path(in: content)
        XCTAssertFalse(shape.contains(point))
        let pixelX = Int(point.x / bounds.width * CGFloat(bitmap.pixelsWide))
        let pixelY = bitmap.pixelsHigh - 1 - Int(point.y / bounds.height * CGFloat(bitmap.pixelsHigh))
        // The raster pixel straddles the edge, so allow antialiasing but not an opaque material fill.
        XCTAssertLessThan(try XCTUnwrap(bitmap.colorAt(x: pixelX, y: pixelY)).alphaComponent, 0.75)
    }

    func testProbeDoesNotForceLayerBackingOnTheSystemFrame() throws {
        _ = NSApplication.shared
        let panel = NSPanel(contentRect: NSRect(x: 0, y: 0, width: 390, height: 700),
                            styleMask: [.borderless], backing: .buffered, defer: false)
        panel.isReleasedWhenClosed = false
        defer { panel.close() }
        let content = NSView()
        panel.contentView = content
        let frame = try XCTUnwrap(content.superview)
        let wantsLayer = frame.wantsLayer
        content.addSubview(MenuWindowCornerView())
        XCTAssertEqual(frame.wantsLayer, wantsLayer)
    }

    func testNewNativeBackgroundIsMaskedAfterAppearanceAndLayoutChanges() async throws {
        _ = NSApplication.shared
        let panel = NSPanel(contentRect: NSRect(x: 0, y: 0, width: 390, height: 700),
                            styleMask: [.borderless], backing: .buffered, defer: false)
        panel.isReleasedWhenClosed = false
        defer { panel.close() }
        let content = NSView(frame: panel.contentLayoutRect)
        panel.contentView = content
        let frame = try XCTUnwrap(content.superview)
        let probe = MenuWindowCornerView()
        content.addSubview(probe)

        let background = NSVisualEffectView(frame: frame.bounds)
        frame.addSubview(background, positioned: .below, relativeTo: content)
        probe.updateAppearance("dark")
        try await Task.sleep(for: .milliseconds(30))
        let originalMask = try XCTUnwrap(background.maskImage)
        probe.updateAppearance("light")
        try await Task.sleep(for: .milliseconds(30))
        XCTAssertTrue(background.maskImage === originalMask, "Unchanged geometry must reuse its mask.")

        background.removeFromSuperview()
        let replacement = NSVisualEffectView(frame: frame.bounds)
        frame.addSubview(replacement, positioned: .below, relativeTo: content)
        probe.needsLayout = true
        probe.layoutSubtreeIfNeeded()
        try await Task.sleep(for: .milliseconds(30))
        XCTAssertNotNil(replacement.maskImage)
        XCTAssertFalse(replacement.maskImage === originalMask)
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

    func testSameWindowSynchronizesAppearanceAfterRepeatedUpdates() async throws {
        _ = NSApplication.shared
        let panel = NSPanel(contentRect: NSRect(x: 0, y: 0, width: 390, height: 700),
                            styleMask: [.borderless], backing: .buffered, defer: false)
        panel.isReleasedWhenClosed = false
        defer { panel.close() }
        let content = NSView()
        panel.contentView = content
        let probe = MenuWindowCornerView()
        content.addSubview(probe)

        for _ in 0..<3 {
            for (preference, name) in [("dark", NSAppearance.Name.darkAqua), ("light", .aqua), ("system", nil)] {
                probe.updateAppearance(preference)
                try await Task.sleep(for: .milliseconds(30))
                XCTAssertEqual(panel.appearance?.name, name)
                XCTAssertFalse(panel.isOpaque)
                XCTAssertEqual(panel.backgroundColor, .clear)
            }
        }
    }
}
