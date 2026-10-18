import AppKit
import XCTest
@testable import TokenCat

@MainActor
final class MenuBarInteractionTests: XCTestCase {
    func testStatusItemClickTogglesOnceAcrossMouseMonitorsAndKeyLoss() async throws {
        _ = NSApplication.shared
        let suite = "TokenCat.MenuBarInteraction.\(UUID().uuidString)"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        let settings = AppSettings(defaults: defaults)
        let model = AppModel(settings: settings, worker: FixtureUsageLoader(result: .success(MenuFixtures.dashboard())))
        let controller = MenuBarController(settings: settings, model: model,
            settingsWindow: SettingsWindowController(settings: settings, model: model), openDashboard: {})
        controller.start()
        defer { controller.stop(); controller.menu.panel.close() }
        let button = try XCTUnwrap(controller.statusItem?.button)
        button.setFrameSize(NSSize(width: 38, height: 24))
        let window = try XCTUnwrap(button.window)
        let localPoint = button.convert(NSPoint(x: button.bounds.midX, y: button.bounds.midY), to: nil)
        var screenPoint = window.convertPoint(toScreen: localPoint)
        let menu = controller.menu
        // Verify that the installed button action runs on press, before focus-loss dismissal.
        let previousMask = button.sendAction(on: [.leftMouseDown, .rightMouseDown])
        XCTAssertEqual(NSEvent.EventTypeMask(rawValue: UInt64(previousMask)), [.leftMouseDown, .rightMouseDown])
        XCTAssertFalse(menu.panel.hidesOnDeactivate)

        for (type, mouseButtons) in [(NSEvent.EventType.leftMouseDown, 1), (.rightMouseDown, 2)] {
            button.performClick(nil)
            XCTAssertTrue(menu.panel.isVisible)
            button.setFrameSize(NSSize(width: 38, height: 24))
            screenPoint = window.convertPoint(toScreen: button.convert(NSPoint(x: button.bounds.midX, y: button.bounds.midY), to: nil))
            // Both local and system-routed/windowless status clicks must reach the same action.
            let press = try XCTUnwrap(NSEvent.mouseEvent(with: type, location: screenPoint, modifierFlags: [],
                timestamp: 0, windowNumber: 0, context: nil, eventNumber: 0, clickCount: 1, pressure: 1))
            XCTAssertNil(press.window)
            XCTAssertTrue(menu.handleMouseDown(press) === press)
            XCTAssertTrue(menu.panel.isVisible, "A windowless press on the icon must not be treated as an outside click.")
            menu.handleGlobalMouseDown(at: screenPoint)
            XCTAssertTrue(menu.panel.isVisible, "The global mouse monitor must leave status clicks to the button.")
            menu.dismissAfterKeyLoss(keyWindow: nil, mouseLocation: screenPoint, mouseButtons: mouseButtons)
            XCTAssertTrue(menu.panel.isVisible, "Dismissal handlers must leave this click for the status item's toggle action.")

            button.performClick(nil)
            XCTAssertFalse(menu.panel.isVisible)
            try await Task.sleep(for: .milliseconds(40))
            XCTAssertFalse(menu.panel.isVisible, "A queued focus callback must not reopen the panel.")
        }

        button.performClick(nil)
        menu.panel.cancelOperation(nil)
        XCTAssertFalse(menu.panel.isVisible)
        button.performClick(nil)
        XCTAssertTrue(menu.panel.isVisible, "Escape must not suppress the next ordinary open.")
        menu.handleGlobalMouseDown(at: NSPoint(x: menu.panel.frame.midX, y: menu.panel.frame.minY - 20))
        XCTAssertFalse(menu.panel.isVisible)
        button.performClick(nil)
        XCTAssertTrue(menu.panel.isVisible, "An outside dismissal must not suppress the next ordinary open.")
        // Pointer hover alone must not prevent keyboard focus changes from closing the menu.
        menu.dismissAfterKeyLoss(keyWindow: nil, mouseLocation: screenPoint, mouseButtons: 0)
        XCTAssertFalse(menu.panel.isVisible)
    }
}
