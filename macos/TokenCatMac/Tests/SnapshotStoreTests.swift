import XCTest
@testable import TokenCatMac

final class SnapshotStoreTests: XCTestCase {
  func testSaveAndLoadSnapshot() throws {
    let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
    let store = SnapshotStore(directoryURL: directory)
    let snapshot = TokenCatSnapshot.placeholder

    try store.save(snapshot)
    let loaded = try store.load()

    XCTAssertEqual(loaded.schemaVersion, snapshot.schemaVersion)
    XCTAssertEqual(loaded.overview.tokenTotals.total, snapshot.overview.tokenTotals.total)
  }

  func testLoadMissingSnapshotThrows() {
    let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
    let store = SnapshotStore(directoryURL: directory)

    XCTAssertThrowsError(try store.load()) { error in
      XCTAssertEqual(error as? SnapshotStoreError, .snapshotNotFound)
    }
  }

  func testDevelopmentDefaultForAppUsesWidgetContainer() throws {
    let bundle = try Self.makeBundle(
      name: "TokenCatMac.app",
      info: [
        "CFBundleIdentifier": "com.example.tokencat",
        "TokenCatWidgetBundleIdentifier": "com.example.tokencat.widget"
      ]
    )

    let store = SnapshotStore.developmentDefault(bundle: bundle)

    XCTAssertTrue(store.directoryURL?.path.hasSuffix("Library/Containers/com.example.tokencat.widget/Data/Library/Application Support/TokenCat") == true)
  }

  private static func makeBundle(name: String, info: [String: String]) throws -> Bundle {
    let bundleURL = FileManager.default.temporaryDirectory
      .appendingPathComponent(UUID().uuidString, isDirectory: true)
      .appendingPathComponent(name, isDirectory: true)
    let contentsURL = bundleURL.appendingPathComponent("Contents", isDirectory: true)
    try FileManager.default.createDirectory(at: contentsURL, withIntermediateDirectories: true)
    let infoURL = contentsURL.appendingPathComponent("Info.plist")
    try (info as NSDictionary).write(to: infoURL)

    guard let bundle = Bundle(url: bundleURL) else {
      throw CocoaError(.fileReadCorruptFile)
    }
    return bundle
  }
}
