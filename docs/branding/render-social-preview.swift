#!/usr/bin/env swift
import AppKit
import CoreGraphics

// A code-native layout using TokenCat's existing vector mark. The task tree is
// a conceptual illustration, not a screenshot or a claim about measured usage.
let project = URL(fileURLWithPath: #filePath)
    .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
let destination = project.appendingPathComponent("docs/assets/github-social-preview.png")
let width = 1280
let height = 640
let space = CGColorSpace(name: CGColorSpace.sRGB)!
let canvas = CGContext(data: nil, width: width, height: height, bitsPerComponent: 8,
                       bytesPerRow: 0, space: space,
                       bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)!
canvas.translateBy(x: 0, y: CGFloat(height))
canvas.scaleBy(x: 1, y: -1)
NSGraphicsContext.current = NSGraphicsContext(cgContext: canvas, flipped: true)

func color(_ hex: UInt32) -> NSColor {
    NSColor(srgbRed: CGFloat((hex >> 16) & 255) / 255,
            green: CGFloat((hex >> 8) & 255) / 255,
            blue: CGFloat(hex & 255) / 255, alpha: 1)
}
let ink = color(0x183633)
let secondary = color(0x526963)
let teal = color(0x147C77)

func box(_ rect: CGRect, fill: NSColor, radius: CGFloat = 0,
         stroke: NSColor? = nil) {
    let path = NSBezierPath(roundedRect: rect, xRadius: radius, yRadius: radius)
    fill.setFill()
    path.fill()
    if let stroke {
        stroke.setStroke()
        path.lineWidth = 1
        path.stroke()
    }
}

func text(_ value: String, x: CGFloat, y: CGFloat, size: CGFloat,
          weight: NSFont.Weight = .regular, tint: NSColor = ink) {
    (value as NSString).draw(at: CGPoint(x: x, y: y), withAttributes: [
        .font: NSFont.systemFont(ofSize: size, weight: weight),
        .foregroundColor: tint,
    ])
}

func line(_ points: [CGPoint], tint: NSColor, thickness: CGFloat = 2) {
    let path = NSBezierPath()
    path.move(to: points[0])
    for point in points.dropFirst() { path.line(to: point) }
    path.lineWidth = thickness
    tint.setStroke()
    path.stroke()
}

box(CGRect(x: 0, y: 0, width: width, height: height), fill: color(0xF5F6F0))
box(CGRect(x: 0, y: 0, width: width, height: 8), fill: teal)

let mark = NSImage(contentsOf: project.appendingPathComponent("macos/Sources/TokenCat/Resources/TokenCatMark.pdf"))!
mark.draw(in: CGRect(x: 66, y: 59, width: 64, height: 54),
          from: .zero, operation: .sourceOver, fraction: 1, respectFlipped: true, hints: nil)
text("TokenCat", x: 147, y: 57, size: 44, weight: .bold)

text("Know where your", x: 64, y: 180, size: 56, weight: .bold)
text("agent tokens go.", x: 64, y: 245, size: 56, weight: .bold)
text("Usage & estimated costs", x: 66, y: 337, size: 28, tint: secondary)
text("for agents and subagents.", x: 66, y: 377, size: 28, tint: secondary)
text("Codex · Claude Code · OpenCode · Antigravity", x: 66, y: 457,
     size: 20, weight: .medium, tint: secondary)

for (label, x, chipWidth) in [("LOCAL RECORDS", 66, 162), ("READ-ONLY", 240, 130), ("macOS + CLI", 382, 149)] {
    box(CGRect(x: x, y: 517, width: chipWidth, height: 38), fill: color(0xE4ECE5), radius: 8)
    text(label, x: CGFloat(x + 14), y: 527, size: 15, weight: .semibold, tint: teal)
}

box(CGRect(x: 746, y: 139, width: 472, height: 422), fill: .white,
    radius: 24, stroke: color(0xDBE4DD))
text("USAGE BY TASK", x: 782, y: 171, size: 17, weight: .semibold, tint: secondary)
text("Agent + subagents", x: 782, y: 205, size: 29, weight: .bold)

box(CGRect(x: 782, y: 264, width: 400, height: 64), fill: color(0xE8F2EC), radius: 12)
text("Parent task", x: 808, y: 275, size: 21, weight: .semibold)
text("Direct usage", x: 808, y: 301, size: 15, tint: secondary)

let branchColor = color(0xB4CFC2)
line([CGPoint(x: 804, y: 328), CGPoint(x: 804, y: 449)], tint: branchColor)
for (index, y) in [(1, 346), (2, 420)] {
    line([CGPoint(x: 804, y: y + 29), CGPoint(x: 827, y: y + 29)], tint: branchColor)
    box(CGRect(x: 827, y: y, width: 355, height: 60), fill: color(0xF5F7F3), radius: 10)
    text("Subagent 0\(index)", x: 849, y: CGFloat(y + 10), size: 20, weight: .medium)
    text("Own contribution", x: 849, y: CGFloat(y + 34), size: 14, tint: secondary)
}
text("One task family. Visible contributions.", x: 782, y: 508,
     size: 19, weight: .medium, tint: teal)
text("github.com/xiaoran007/TokenCat", x: 66, y: 592, size: 17, tint: secondary)

let bitmap = NSBitmapImageRep(cgImage: canvas.makeImage()!)
try FileManager.default.createDirectory(at: destination.deletingLastPathComponent(), withIntermediateDirectories: true)
try bitmap.representation(using: .png, properties: [:])!.write(to: destination)
print(destination.path)
