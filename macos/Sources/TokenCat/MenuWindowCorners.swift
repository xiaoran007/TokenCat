import AppKit
import SwiftUI

/// Synchronize the menu's native material after attachment, layout and appearance updates.
struct MenuWindowCorners: NSViewRepresentable {
    var appearance = "system"
    func makeNSView(context: Context) -> MenuWindowCornerView {
        let view = MenuWindowCornerView()
        view.updateAppearance(appearance)
        return view
    }
    func updateNSView(_ nsView: MenuWindowCornerView, context: Context) {
        nsView.updateAppearance(appearance)
    }
}

final class MenuWindowCornerView: NSView {
    static let cornerRadius: CGFloat = 24
    static func materialMask(bounds: NSRect, contentRect: NSRect) -> NSImage {
        // Continuous corners change with the rectangle's proportions; never stretch a tiny square mask.
        let rect = contentRect.offsetBy(dx: -bounds.minX, dy: -bounds.minY)
        return NSImage(size: bounds.size, flipped: false) { _ in
            guard let context = NSGraphicsContext.current?.cgContext else { return false }
            context.addPath(RoundedRectangle(cornerRadius: cornerRadius, style: .continuous).path(in: rect).cgPath)
            context.setFillColor(NSColor.black.cgColor)
            context.fillPath()
            return true
        }
    }
    private struct BackgroundMask {
        let bounds: NSRect
        let contentRect: NSRect
        let image: NSImage
    }
    private var backgroundMasks: [ObjectIdentifier: BackgroundMask] = [:]
    private var requestedAppearance = "system"
    private var updatePending = false

    func updateAppearance(_ appearance: String) {
        requestedAppearance = appearance
        scheduleUpdate()
    }

    override func viewDidMoveToWindow() {
        super.viewDidMoveToWindow()
        synchronizeWindow()
        scheduleUpdate()
    }

    override func viewDidChangeEffectiveAppearance() {
        super.viewDidChangeEffectiveAppearance()
        scheduleUpdate()
    }

    override func layout() {
        super.layout()
        scheduleUpdate()
    }

    private func scheduleUpdate() {
        guard !updatePending else { return }
        updatePending = true
        DispatchQueue.main.async { [weak self] in
            guard let self else { return }
            self.updatePending = false
            self.synchronizeWindow()
        }
    }

    private func synchronizeWindow() {
        guard let window, let content = window.contentView, let frame = content.superview else { return }
        let desired = requestedAppearance == "light" ? NSAppearance.Name.aqua
            : requestedAppearance == "dark" ? .darkAqua : nil
        if window.appearance?.name != desired { window.appearance = desired.flatMap(NSAppearance.init(named:)) }
        var changed = false
        if window.isOpaque { window.isOpaque = false; changed = true }
        if window.backgroundColor != .clear { window.backgroundColor = .clear; changed = true }

        // Do not force layer backing on the system frame and its entire SwiftUI subtree.
        if let layer = frame.layer,
           layer.cornerRadius != Self.cornerRadius || layer.cornerCurve != .continuous || !layer.masksToBounds {
            layer.cornerRadius = Self.cornerRadius
            layer.cornerCurve = .continuous
            layer.masksToBounds = true
            changed = true
        }

        // A window material has its own mask; a content-layer clip alone does not configure it.
        let backgrounds = windowBackgrounds(frame: frame, content: content)
        let identifiers = Set(backgrounds.map(ObjectIdentifier.init))
        backgroundMasks = backgroundMasks.filter { identifiers.contains($0.key) }
        for effect in backgrounds {
            let id = ObjectIdentifier(effect)
            let contentRect = effect.convert(content.bounds, from: content)
            if backgroundMasks[id]?.bounds != effect.bounds || backgroundMasks[id]?.contentRect != contentRect {
                backgroundMasks[id] = BackgroundMask(bounds: effect.bounds, contentRect: contentRect,
                    image: Self.materialMask(bounds: effect.bounds, contentRect: contentRect))
            }
            if let mask = backgroundMasks[id]?.image, effect.maskImage !== mask {
                effect.maskImage = mask
                changed = true
            }
        }
        if changed { window.invalidateShadow() }
    }

    private func windowBackgrounds(frame: NSView, content: NSView) -> [NSVisualEffectView] {
        guard !content.bounds.isEmpty else { return [] }
        func backgrounds(in view: NSView) -> [NSVisualEffectView] {
            // Leave SwiftUI's internal card materials and glass layers alone.
            if view === content {
                return (view as? NSVisualEffectView).map { [$0] } ?? []
            }
            let match = (view as? NSVisualEffectView).flatMap { effect -> NSVisualEffectView? in
                let bounds = effect.convert(effect.bounds, to: content)
                return effect.blendingMode == .behindWindow && bounds.contains(content.bounds) ? effect : nil
            }
            return (match.map { [$0] } ?? []) + view.subviews.flatMap { backgrounds(in: $0) }
        }
        return backgrounds(in: frame)
    }
}
