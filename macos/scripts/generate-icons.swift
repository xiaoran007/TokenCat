#!/usr/bin/env swift
import AppKit
import CoreGraphics

// The approved C concept, redrawn as curves. This is the single source for the
// SVG, vector PDF templates, and app icon; no image tools or dependencies needed.
let root = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
let artwork = root.appendingPathComponent("Branding")
let resources = root.appendingPathComponent("Sources/TokenCat/Resources")
let fileManager = FileManager.default
try fileManager.createDirectory(at: artwork, withIntermediateDirectories: true)
try fileManager.createDirectory(at: resources, withIntermediateDirectories: true)

let markSize = CGSize(width: 512, height: 432)
let teal = CGColor(colorSpace: CGColorSpace(name: CGColorSpace.sRGB)!,
                   components: [20 / 255, 124 / 255, 119 / 255, 1])!

func catPath(menu: Bool = false) -> CGPath {
    let path = CGMutablePath()
    path.move(to: CGPoint(x: 78, y: 18))
    path.addCurve(to: CGPoint(x: 189, y: 77), control1: CGPoint(x: 109, y: 18), control2: CGPoint(x: 151, y: 50))
    path.addCurve(to: CGPoint(x: 323, y: 77), control1: CGPoint(x: 230, y: 66), control2: CGPoint(x: 282, y: 66))
    path.addCurve(to: CGPoint(x: 434, y: 18), control1: CGPoint(x: 361, y: 50), control2: CGPoint(x: 403, y: 18))
    path.addCurve(to: CGPoint(x: 461, y: 162), control1: CGPoint(x: 457, y: 18), control2: CGPoint(x: 470, y: 96))
    path.addCurve(to: CGPoint(x: 496, y: 278), control1: CGPoint(x: 484, y: 198), control2: CGPoint(x: 496, y: 240))
    path.addCurve(to: CGPoint(x: 256, y: 416), control1: CGPoint(x: 496, y: 366), control2: CGPoint(x: 408, y: 416))
    path.addCurve(to: CGPoint(x: 16, y: 278), control1: CGPoint(x: 104, y: 416), control2: CGPoint(x: 16, y: 366))
    path.addCurve(to: CGPoint(x: 51, y: 162), control1: CGPoint(x: 16, y: 240), control2: CGPoint(x: 28, y: 198))
    path.addCurve(to: CGPoint(x: 78, y: 18), control1: CGPoint(x: 42, y: 96), control2: CGPoint(x: 55, y: 18))
    path.closeSubpath()

    let ear = CGMutablePath()
    ear.move(to: CGPoint(x: 88, y: 62))
    ear.addCurve(to: CGPoint(x: 137, y: 107), control1: CGPoint(x: 102, y: 65), control2: CGPoint(x: 124, y: 89))
    ear.addCurve(to: CGPoint(x: 84, y: 136), control1: CGPoint(x: 116, y: 116), control2: CGPoint(x: 96, y: 126))
    ear.addCurve(to: CGPoint(x: 88, y: 62), control1: CGPoint(x: 80, y: 110), control2: CGPoint(x: 79, y: 81))
    ear.closeSubpath()
    path.addPath(ear)
    path.addPath(ear, transform: CGAffineTransform(a: -1, b: 0, c: 0, d: 1, tx: 512, ty: 0))

    // Slightly wider cutouts and a stronger smile retain the expression at 18pt.
    let eyeWidth: CGFloat = menu ? 52 : 46
    for center: CGFloat in [159, 353] {
        path.addEllipse(in: CGRect(x: center - eyeWidth / 2, y: 211, width: eyeWidth, height: 68))
    }
    path.move(to: CGPoint(x: 234, y: 274))
    path.addLine(to: CGPoint(x: 278, y: 274))
    path.addQuadCurve(to: CGPoint(x: 282, y: 283), control: CGPoint(x: 287, y: 274))
    path.addLine(to: CGPoint(x: 263, y: 305))
    path.addQuadCurve(to: CGPoint(x: 249, y: 305), control: CGPoint(x: 256, y: 313))
    path.addLine(to: CGPoint(x: 230, y: 283))
    path.addQuadCurve(to: CGPoint(x: 234, y: 274), control: CGPoint(x: 225, y: 274))
    path.closeSubpath()

    // An explicit closed outline avoids overlaps at the center of a stroked W.
    let lowerCheek: CGFloat = menu ? 364 : 358
    path.move(to: CGPoint(x: 207, y: 330))
    path.addCurve(to: CGPoint(x: 220, y: 328), control1: CGPoint(x: 205, y: 324), control2: CGPoint(x: 216, y: 319))
    path.addCurve(to: CGPoint(x: 250, y: 323), control1: CGPoint(x: 226, y: 342), control2: CGPoint(x: 243, y: 340))
    path.addCurve(to: CGPoint(x: 262, y: 323), control1: CGPoint(x: 252, y: 315), control2: CGPoint(x: 260, y: 315))
    path.addCurve(to: CGPoint(x: 292, y: 328), control1: CGPoint(x: 269, y: 340), control2: CGPoint(x: 286, y: 342))
    path.addCurve(to: CGPoint(x: 305, y: 330), control1: CGPoint(x: 296, y: 319), control2: CGPoint(x: 307, y: 324))
    path.addCurve(to: CGPoint(x: 256, y: 338), control1: CGPoint(x: 298, y: lowerCheek - 5), control2: CGPoint(x: 273, y: lowerCheek))
    path.addCurve(to: CGPoint(x: 207, y: 330), control1: CGPoint(x: 239, y: lowerCheek), control2: CGPoint(x: 214, y: lowerCheek - 5))
    path.closeSubpath()
    return path
}

func drawMark(_ context: CGContext, in rect: CGRect, menu: Bool = false, color: CGColor = teal) {
    context.saveGState()
    context.translateBy(x: rect.minX, y: rect.minY)
    context.scaleBy(x: rect.width / markSize.width, y: rect.height / markSize.height)
    context.setFillColor(color)
    context.addPath(catPath(menu: menu))
    context.drawPath(using: .eoFill)
    context.restoreGState()
}

func writePDF(name: String, menu: Bool) throws {
    let data = NSMutableData()
    var bounds = CGRect(origin: .zero, size: markSize)
    let consumer = CGDataConsumer(data: data)!
    let context = CGContext(consumer: consumer, mediaBox: &bounds, nil)!
    context.beginPDFPage(nil)
    context.translateBy(x: 0, y: markSize.height)
    context.scaleBy(x: 1, y: -1)
    drawMark(context, in: bounds, menu: menu, color: CGColor(gray: 0, alpha: 1))
    context.endPDFPage()
    context.closePDF()
    try (data as Data).write(to: resources.appendingPathComponent(name))
}

func svgPath(_ path: CGPath) -> String {
    var commands: [String] = []
    func point(_ p: CGPoint) -> String { String(format: "%.3f %.3f", locale: Locale(identifier: "en_US_POSIX"), p.x, p.y) }
    path.applyWithBlock { entry in
        let element = entry.pointee
        switch element.type {
        case .moveToPoint: commands.append("M \(point(element.points[0]))")
        case .addLineToPoint: commands.append("L \(point(element.points[0]))")
        case .addQuadCurveToPoint: commands.append("Q \(point(element.points[0])) \(point(element.points[1]))")
        case .addCurveToPoint: commands.append("C \(point(element.points[0])) \(point(element.points[1])) \(point(element.points[2]))")
        case .closeSubpath: commands.append("Z")
        @unknown default: preconditionFailure("Unsupported curve")
        }
    }
    return commands.joined(separator: " ")
}

func writePNG(to url: URL, size: Int, draw: (CGContext) -> Void) throws {
    let context = CGContext(data: nil, width: size, height: size, bitsPerComponent: 8, bytesPerRow: 0,
                            space: CGColorSpace(name: CGColorSpace.sRGB)!, bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)!
    context.scaleBy(x: CGFloat(size) / 1024, y: CGFloat(size) / 1024)
    context.translateBy(x: 0, y: 1024)
    context.scaleBy(x: 1, y: -1)
    draw(context)
    let bitmap = NSBitmapImageRep(cgImage: context.makeImage()!)
    try bitmap.representation(using: .png, properties: [:])!.write(to: url)
}

func drawAppIcon(_ context: CGContext) {
    let tile = CGPath(roundedRect: CGRect(x: 100, y: 100, width: 824, height: 824),
                      cornerWidth: 184, cornerHeight: 184, transform: nil)
    context.saveGState()
    context.setShadow(offset: CGSize(width: 0, height: 10), blur: 22, color: CGColor(gray: 0, alpha: 0.16))
    context.setFillColor(CGColor(red: 0.83, green: 0.95, blue: 0.91, alpha: 1))
    context.addPath(tile)
    context.fillPath()
    context.restoreGState()
    context.saveGState()
    context.addPath(tile)
    context.clip()
    let gradient = CGGradient(colorsSpace: CGColorSpace(name: CGColorSpace.sRGB),
        colors: [CGColor(red: 0.91, green: 0.99, blue: 0.96, alpha: 1),
                 CGColor(red: 0.79, green: 0.93, blue: 0.88, alpha: 1)] as CFArray, locations: [0, 1])!
    context.drawLinearGradient(gradient, start: CGPoint(x: 330, y: 100), end: CGPoint(x: 700, y: 924),
                               options: [.drawsBeforeStartLocation, .drawsAfterEndLocation])
    context.restoreGState()
    context.addPath(tile)
    context.setStrokeColor(CGColor(red: 0.7, green: 0.85, blue: 0.8, alpha: 0.6))
    context.setLineWidth(2)
    context.strokePath()
    drawMark(context, in: CGRect(x: 208, y: 236, width: 608, height: 513))
}

let svg = """
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 432" role="img" aria-label="TokenCat">
  <path fill="#147C77" fill-rule="evenodd" d="\(svgPath(catPath()))"/>
</svg>

"""
try svg.write(to: artwork.appendingPathComponent("TokenCat.svg"), atomically: true, encoding: .utf8)
try writePDF(name: "TokenCatMark.pdf", menu: false)
try writePDF(name: "TokenCatMenuMark.pdf", menu: true)
try writePNG(to: artwork.appendingPathComponent("TokenCatAppIcon.png"), size: 1024, draw: drawAppIcon)

let iconset = fileManager.temporaryDirectory.appendingPathComponent("TokenCat-\(UUID().uuidString).iconset")
try fileManager.createDirectory(at: iconset, withIntermediateDirectories: true)
defer { try? fileManager.removeItem(at: iconset) }
for size in [16, 32, 128, 256, 512] {
    for scale in [1, 2] {
        let suffix = scale == 2 ? "@2x" : ""
        try writePNG(to: iconset.appendingPathComponent("icon_\(size)x\(size)\(suffix).png"), size: size * scale, draw: drawAppIcon)
    }
}
let iconutil = Process()
iconutil.executableURL = URL(fileURLWithPath: "/usr/bin/iconutil")
iconutil.arguments = ["--convert", "icns", "--output", artwork.appendingPathComponent("TokenCat.icns").path, iconset.path]
try iconutil.run()
iconutil.waitUntilExit()
guard iconutil.terminationStatus == 0 else { exit(iconutil.terminationStatus) }
print("Generated TokenCat SVG, PDF templates, PNG, and ICNS in macos/Branding and app Resources.")
