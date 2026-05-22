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
}
