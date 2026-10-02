// swift-tools-version: 5.9
import PackageDescription
import Foundation

let root = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
let package = Package(
    name: "TokenCatMac",
    defaultLocalization: "en-US",
    platforms: [.macOS(.v14)],
    products: [.executable(name: "TokenCat", targets: ["TokenCat"])],
    targets: [
        .systemLibrary(name: "CTokenCat"),
        .target(name: "TokenCatKit", resources: [.process("Resources")]),
        .executableTarget(name: "TokenCat", dependencies: ["TokenCatKit", "CTokenCat"],
            linkerSettings: [.unsafeFlags(["-L", root.appendingPathComponent("native/target/release").path]),
                             .linkedLibrary("tokencat_core"), .linkedLibrary("sqlite3"),
                             .linkedFramework("Security"), .linkedFramework("SystemConfiguration")]),
        .testTarget(name: "TokenCatKitTests", dependencies: ["TokenCatKit"]),
        .testTarget(name: "TokenCatAppTests", dependencies: ["TokenCat", "TokenCatKit"])
    ]
)
