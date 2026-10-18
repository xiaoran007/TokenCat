import AppKit
import SwiftUI
import XCTest
@testable import TokenCat

@MainActor
final class MenuWindowCornerTests: XCTestCase {
    func testMenuOwnsItsOnlyWindowMaterialAndClipsItsShadow() throws {
        try withController { controller, _ in
            let panel = controller.panel
            let material = controller.material
            XCTAssertTrue(panel.contentView === material, "AppKit only guarantees a masked window shadow when the effect is the content view.")
            XCTAssertFalse(panel.isOpaque)
            XCTAssertEqual(panel.backgroundColor, .clear)
            XCTAssertEqual(panel.styleMask, [.borderless, .nonactivatingPanel])
            XCTAssertTrue(panel.hasShadow)
            XCTAssertTrue(panel.canBecomeKey)
            XCTAssertFalse(panel.canBecomeMain)
            XCTAssertEqual(material.blendingMode, .behindWindow)
            XCTAssertEqual(material.material, .popover)
            XCTAssertEqual(material.bounds.size, panel.contentLayoutRect.size)
            let frame = try XCTUnwrap(material.superview)
            XCTAssertEqual(frame.subviews.compactMap { $0 as? NSVisualEffectView }.count, 1,
                           "There must be no second rectangular window material behind the rounded content.")
            try assertMask(material)
        }
    }

    func testActualMenuKeepsItsRootMaterialAcrossAppearanceAndPresetChanges() async throws {
        _ = NSApplication.shared
        let suite = "TokenCat.MenuNativeTransitions.\(UUID().uuidString)"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        let settings = AppSettings(defaults: defaults)
        let model = AppModel(settings: settings, worker: FixtureUsageLoader(result: .success(MenuFixtures.dashboard())))
        let controller = MenuPanelController(settings: settings, model: model,
            settingsWindow: SettingsWindowController(settings: settings, model: model), openDashboard: {})
        defer { controller.hide(); controller.panel.close() }
        let material = controller.material
        let content = try XCTUnwrap(material.subviews.first)
        for _ in 0..<2 {
            for (appearance, name) in [("light", NSAppearance.Name.aqua), ("dark", .darkAqua), ("system", nil)] {
                for preset in MenuPanelStyle.allCases {
                    settings.appearance = appearance
                    settings.menuStyle = preset
                    controller.updateAppearance(appearance)
                    try await Task.sleep(for: .milliseconds(40))
                    controller.resizeToFit()
                    XCTAssertTrue(controller.panel.contentView === material)
                    XCTAssertTrue(material.subviews.first === content)
                    XCTAssertEqual(controller.panel.appearance?.name, name)
                    XCTAssertEqual(controller.panel.backgroundColor, .clear)
                    try assertMask(material)
                }
            }
        }
    }

    func testMaskTracksWindowSizeWithoutStretchingOrRecreatingUnchangedGeometry() throws {
        try withController { controller, _ in
            let panel = controller.panel
            let material = controller.material
            let original = try XCTUnwrap(material.maskImage)
            material.needsLayout = true
            material.layoutSubtreeIfNeeded()
            XCTAssertTrue(material.maskImage === original)
            panel.setContentSize(NSSize(width: 390, height: 580))
            material.layoutSubtreeIfNeeded()
            XCTAssertFalse(material.maskImage === original)
            try assertMask(material)
        }
    }

    func testEscapeDismissesTheNativeMenu() throws {
        try withController { controller, _ in
            controller.panel.orderFront(nil)
            XCTAssertTrue(controller.panel.isVisible)
            controller.panel.cancelOperation(nil)
            XCTAssertFalse(controller.panel.isVisible)
        }
    }

    func testMenuFitsTheAvailableHeightOfTheAnchorScreen() throws {
        try withController { controller, _ in
            controller.resizeToFit(maximumHeight: 480)
            XCTAssertLessThanOrEqual(controller.panel.frame.height, 480)
            XCTAssertGreaterThan(controller.panel.frame.height, 300)
            XCTAssertEqual(controller.material.bounds.size, controller.panel.contentLayoutRect.size)
            try assertMask(controller.material)
        }
    }

    func testHelpWindowsBelongToTheMenuButOtherAppWindowsDoNot() throws {
        try withController { controller, _ in
            let help = NSPanel(contentRect: .zero, styleMask: [.borderless], backing: .buffered, defer: false)
            let unrelated = NSPanel(contentRect: .zero, styleMask: [.borderless], backing: .buffered, defer: false)
            help.isReleasedWhenClosed = false
            unrelated.isReleasedWhenClosed = false
            defer { help.close(); unrelated.close() }
            controller.panel.addChildWindow(help, ordered: .above)
            XCTAssertTrue(controller.contains(window: help))
            XCTAssertTrue(controller.contains(window: controller.panel))
            XCTAssertFalse(controller.contains(window: unrelated))
            XCTAssertFalse(controller.contains(window: nil))
        }
    }

    func testRealHelpPopoverKeepsItsParentMenuVisible() async throws {
        _ = NSApplication.shared
        let suite = "TokenCat.MenuPopoverTests.\(UUID().uuidString)"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        let settings = AppSettings(defaults: defaults)
        let model = AppModel(settings: settings, worker: FixtureUsageLoader(result: .success(MenuFixtures.dashboard())))
        let controller = MenuPanelController(settings: settings, model: model,
            settingsWindow: SettingsWindowController(settings: settings, model: model), openDashboard: {})
        let popover = NSPopover()
        let content = NSViewController()
        content.view = NSView(frame: NSRect(x: 0, y: 0, width: 200, height: 100))
        popover.contentViewController = content
        popover.behavior = .transient
        defer { popover.close(); controller.hide(); controller.panel.close() }
        controller.panel.makeKeyAndOrderFront(nil)
        popover.show(relativeTo: NSRect(x: 100, y: 200, width: 20, height: 20),
                     of: controller.material, preferredEdge: .maxX)
        try await Task.sleep(for: .milliseconds(60))
        XCTAssertTrue(popover.isShown)
        XCTAssertTrue(controller.panel.isVisible)
        XCTAssertTrue(controller.contains(window: content.view.window), "Real AppKit help popovers must be recognized as part of the menu.")
    }

    func testAnchorPlacementStaysOnTheSelectedScreen() {
        let screen = NSRect(x: -1440, y: 0, width: 1440, height: 875)
        let size = NSSize(width: 390, height: 700)
        // Center below the item when there is room; clamp only at the screen edges.
        for (x, expectedMinX): (CGFloat, CGFloat) in [(-1435, -1432), (-800, -983), (-20, -398)] {
            let anchor = NSRect(x: x, y: 875, width: 24, height: 25)
            let frame = MenuPanelController.frame(size: size, anchor: anchor, visibleFrame: screen)
            XCTAssertEqual(frame.minX, expectedMinX)
            XCTAssertGreaterThanOrEqual(frame.minX, screen.minX + 8)
            XCTAssertLessThanOrEqual(frame.maxX, screen.maxX - 8)
            XCTAssertGreaterThanOrEqual(frame.minY, screen.minY + 8)
            XCTAssertLessThan(frame.maxY, anchor.minY)
        }
        let shortScreen = NSRect(x: 0, y: 0, width: 1024, height: 600)
        let anchor = NSRect(x: 900, y: 600, width: 24, height: 25)
        let frame = MenuPanelController.frame(size: size, anchor: anchor, visibleFrame: shortScreen)
        XCTAssertTrue(shortScreen.contains(frame))
        XCTAssertLessThan(frame.maxY, anchor.minY)
    }

    private func assertMask(_ material: MenuMaterialView, file: StaticString = #filePath, line: UInt = #line) throws {
        let image = try XCTUnwrap(material.maskImage, file: file, line: line)
        XCTAssertEqual(image.size, material.bounds.size, file: file, line: line)
        let bitmap = try XCTUnwrap(NSBitmapImageRep(data: try XCTUnwrap(image.tiffRepresentation)))
        for x in [0, bitmap.pixelsWide - 1] {
            for y in [0, bitmap.pixelsHigh - 1] {
                XCTAssertEqual(try XCTUnwrap(bitmap.colorAt(x: x, y: y)).alphaComponent, 0, accuracy: 0.01,
                               "The material must be completely transparent outside every rounded corner.", file: file, line: line)
            }
        }
        XCTAssertEqual(try XCTUnwrap(bitmap.colorAt(x: bitmap.pixelsWide / 2, y: bitmap.pixelsHigh / 2)).alphaComponent,
                       1, accuracy: 0.01, file: file, line: line)
    }

    private func withController(_ body: (MenuPanelController, AppSettings) throws -> Void) throws {
        _ = NSApplication.shared
        let suite = "TokenCat.MenuWindowCornerTests.\(UUID().uuidString)"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        let settings = AppSettings(defaults: defaults)
        let model = AppModel(settings: settings, worker: FixtureUsageLoader(result: .success(MenuFixtures.dashboard())))
        let controller = MenuPanelController(settings: settings, model: model,
            settingsWindow: SettingsWindowController(settings: settings, model: model), openDashboard: {})
        defer { controller.hide(); controller.panel.close() }
        try body(controller, settings)
    }
}
