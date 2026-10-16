import AppKit
import SwiftUI

/// The material is the window's content view, so AppKit uses its mask for the window shadow too.
final class MenuMaterialView: NSVisualEffectView {
    static let cornerRadius: CGFloat = 24
    private var maskedBounds = NSRect.zero

    override init(frame frameRect: NSRect) {
        super.init(frame: frameRect)
        material = .popover
        blendingMode = .behindWindow
        state = .active
        updateMask()
    }

    @available(*, unavailable)
    required init?(coder: NSCoder) { fatalError("Menu materials are created programmatically.") }

    override func layout() {
        super.layout()
        updateMask()
    }

    private func updateMask() {
        guard !bounds.isEmpty, maskedBounds != bounds else { return }
        maskedBounds = bounds
        let rect = NSRect(origin: .zero, size: bounds.size)
        maskImage = NSImage(size: rect.size, flipped: false) { _ in
            guard let context = NSGraphicsContext.current?.cgContext else { return false }
            context.addPath(RoundedRectangle(cornerRadius: Self.cornerRadius, style: .continuous).path(in: rect).cgPath)
            context.setFillColor(NSColor.black.cgColor)
            context.fillPath()
            return true
        }
        window?.invalidateShadow()
    }
}

final class MenuNativePanel: NSPanel {
    var onDismiss: (() -> Void)?
    override var canBecomeKey: Bool { true }
    override var canBecomeMain: Bool { false }
    override func cancelOperation(_ sender: Any?) { onDismiss?() }
}

@MainActor
final class MenuPanelController: NSObject, NSWindowDelegate {
    let panel: MenuNativePanel
    let material: MenuMaterialView
    private let host: NSHostingController<MenuHostedContent>
    private var localMonitor: Any?
    private var globalMonitor: Any?
    private weak var anchorWindow: NSWindow?
    private weak var anchorButton: NSStatusBarButton?
    private var maximumHeight: CGFloat?

    init(settings: AppSettings, model: AppModel, settingsWindow: SettingsWindowController,
         openDashboard: @escaping () -> Void) {
        panel = MenuNativePanel(contentRect: NSRect(x: 0, y: 0, width: 390, height: 700),
                                styleMask: [.borderless, .nonactivatingPanel], backing: .buffered, defer: false)
        material = MenuMaterialView(frame: panel.contentLayoutRect)
        host = NSHostingController(rootView: MenuHostedContent(settings: settings, model: model,
            settingsWindow: settingsWindow, openDashboard: openDashboard, openSettings: { settingsWindow.open() }))
        super.init()
        panel.isReleasedWhenClosed = false
        panel.isOpaque = false
        panel.backgroundColor = .clear
        panel.hasShadow = true
        panel.level = .popUpMenu
        panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .transient, .ignoresCycle]
        panel.identifier = NSUserInterfaceItemIdentifier("tokencat-menu")
        panel.delegate = self
        panel.onDismiss = { [weak self] in self?.hide() }
        panel.contentView = material
        host.rootView.openDashboard = { [weak self] in self?.hide(); openDashboard() }
        host.rootView.openSettings = { [weak self] in self?.hide(); settingsWindow.open() }
        host.view.translatesAutoresizingMaskIntoConstraints = false
        material.addSubview(host.view)
        NSLayoutConstraint.activate([
            host.view.leadingAnchor.constraint(equalTo: material.leadingAnchor),
            host.view.trailingAnchor.constraint(equalTo: material.trailingAnchor),
            host.view.topAnchor.constraint(equalTo: material.topAnchor),
            host.view.bottomAnchor.constraint(equalTo: material.bottomAnchor)
        ])
        updateAppearance(settings.appearance)
        resizeToFit()
    }

    func updateAppearance(_ appearance: String) {
        panel.appearance = appearance == "light" ? NSAppearance(named: .aqua)
            : appearance == "dark" ? NSAppearance(named: .darkAqua) : nil
    }

    func resizeToFit(maximumHeight: CGFloat? = nil) {
        if let maximumHeight { self.maximumHeight = maximumHeight }
        // Measure the chrome instead of assuming the same footer height for every locale/preset.
        host.rootView.viewportHeight = 560
        var size = host.sizeThatFits(in: NSSize(width: 390, height: 0))
        if let maximumHeight = self.maximumHeight {
            let chromeHeight = size.height - 560
            host.rootView.viewportHeight = min(560, max(0, maximumHeight - chromeHeight))
            size = host.sizeThatFits(in: NSSize(width: 390, height: 0))
        }
        panel.setContentSize(NSSize(width: 390, height: ceil(size.height)))
        material.layoutSubtreeIfNeeded()
    }

    static func frame(size: NSSize, anchor: NSRect, visibleFrame: NSRect) -> NSRect {
        let availableHeight = min(visibleFrame.maxY, anchor.minY - 6) - visibleFrame.minY - 8
        let fittedSize = NSSize(width: size.width, height: min(size.height, availableHeight))
        let x = max(visibleFrame.minX + 8, min(anchor.midX - fittedSize.width / 2, visibleFrame.maxX - fittedSize.width - 8))
        let y = max(visibleFrame.minY + 8, anchor.minY - fittedSize.height - 6)
        return NSRect(origin: NSPoint(x: x, y: y), size: fittedSize)
    }

    func show(relativeTo button: NSStatusBarButton) {
        guard let window = button.window, let screen = window.screen else { return }
        anchorWindow = window
        anchorButton = button
        let anchor = window.convertToScreen(button.convert(button.bounds, to: nil))
        maximumHeight = min(screen.visibleFrame.maxY, anchor.minY - 6) - screen.visibleFrame.minY - 8
        resizeToFit()
        panel.setFrame(Self.frame(size: panel.frame.size, anchor: anchor, visibleFrame: screen.visibleFrame), display: false)
        panel.makeKeyAndOrderFront(nil)
        button.highlight(true)
        installMonitors()
    }

    func hide() {
        panel.orderOut(nil)
        anchorButton?.highlight(false)
        if let localMonitor { NSEvent.removeMonitor(localMonitor) }
        if let globalMonitor { NSEvent.removeMonitor(globalMonitor) }
        localMonitor = nil
        globalMonitor = nil
    }

    func windowDidResignKey(_ notification: Notification) {
        // SwiftUI help popovers can become key; keep their parent menu visible.
        DispatchQueue.main.async { [weak self] in
            guard let self, self.panel.isVisible else { return }
            if !self.contains(window: NSApp.keyWindow) { self.hide() }
        }
    }

    func contains(window: NSWindow?) -> Bool {
        var candidate = window
        while let current = candidate {
            if current === panel { return true }
            candidate = current.parent
        }
        return false
    }

    private func installMonitors() {
        guard localMonitor == nil else { return }
        localMonitor = NSEvent.addLocalMonitorForEvents(matching: [.leftMouseDown, .rightMouseDown]) { [weak self] event in
            guard let self else { return event }
            if event.window === self.panel {
                let rect = self.material.bounds
                let point = self.material.convert(event.locationInWindow, from: nil)
                if !RoundedRectangle(cornerRadius: MenuMaterialView.cornerRadius, style: .continuous).path(in: rect).contains(point) {
                    self.hide()
                    return nil
                }
            } else if event.window !== self.anchorWindow && !self.contains(window: event.window) {
                self.hide()
            }
            return event
        }
        globalMonitor = NSEvent.addGlobalMonitorForEvents(matching: [.leftMouseDown, .rightMouseDown]) { [weak self] _ in
            self?.hide()
        }
    }
}

private struct MenuHostedContent: View {
    @ObservedObject var settings: AppSettings
    let model: AppModel
    let settingsWindow: SettingsWindowController
    var openDashboard: () -> Void
    var openSettings: () -> Void
    var viewportHeight: CGFloat = 560

    var body: some View {
        MenuPanel(openDashboard: openDashboard, openSettings: openSettings, viewportHeight: viewportHeight)
            .environmentObject(model)
            .environmentObject(settings)
            .environmentObject(settingsWindow)
            .environment(\.locale, settings.language.locale)
            .preferredColorScheme(settings.colorScheme)
    }
}
