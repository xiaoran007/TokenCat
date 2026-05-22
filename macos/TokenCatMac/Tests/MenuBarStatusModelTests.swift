import XCTest
@testable import TokenCatMac

@MainActor
final class MenuBarStatusModelTests: XCTestCase {
  func testLoadCachedSnapshot() throws {
    let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
    let store = SnapshotStore(directoryURL: directory)
    try store.save(.placeholder)

    let model = MenuBarStatusModel(
      bridge: TokenCatBridge(pythonURL: URL(fileURLWithPath: "/bin/echo"), repositoryRootURL: URL(fileURLWithPath: "/tmp"), runner: FakeRunner(result: ProcessResult(stdout: Data(SnapshotTests.sampleSnapshot.utf8), stderr: "", terminationStatus: 0))),
      store: store
    )

    XCTAssertEqual(model.snapshot?.schemaVersion, 1)
    XCTAssertNil(model.errorMessage)
  }

  func testRefreshWritesSnapshot() async throws {
    let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
    let store = SnapshotStore(directoryURL: directory)
    let model = MenuBarStatusModel(
      bridge: TokenCatBridge(pythonURL: URL(fileURLWithPath: "/bin/echo"), repositoryRootURL: URL(fileURLWithPath: "/tmp"), runner: FakeRunner(result: ProcessResult(stdout: Data(SnapshotTests.sampleSnapshot.utf8), stderr: "", terminationStatus: 0))),
      store: store
    )

    await model.refreshNow()

    XCTAssertEqual(model.snapshot?.overview.sessionCount, 2)
    XCTAssertEqual(try store.load().overview.sessionCount, 2)
  }
}
