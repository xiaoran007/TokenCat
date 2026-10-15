import AppKit
import SwiftUI

/// Clip the native frame as well as its content so the system material shares one outline.
struct MenuWindowCorners: NSViewRepresentable {
    func makeNSView(context: Context) -> MenuWindowCornerView { MenuWindowCornerView() }
    func updateNSView(_ nsView: MenuWindowCornerView, context: Context) {}
}

final class MenuWindowCornerView: NSView {
    static let cornerRadius: CGFloat = 24

    override func viewDidMoveToWindow() {
        super.viewDidMoveToWindow()
        guard let window, let frame = window.contentView?.superview else { return }
        window.isOpaque = false
        window.backgroundColor = .clear
        frame.wantsLayer = true
        frame.layer?.cornerRadius = Self.cornerRadius
        frame.layer?.cornerCurve = .continuous
        frame.layer?.masksToBounds = true
        window.invalidateShadow()
    }
}
