import Foundation
import XCTest
@testable import TokenCatMac

final class TokenCatBridgeTests: XCTestCase {
  func testFetchSnapshotDecodesProcessOutput() throws {
    let runner = FakeRunner(result: ProcessResult(stdout: Data(SnapshotTests.sampleSnapshot.utf8), stderr: "", terminationStatus: 0))
    let bridge = TokenCatBridge(
      pythonURL: URL(fileURLWithPath: "/bin/echo"),
      repositoryRootURL: URL(fileURLWithPath: "/tmp"),
      runner: runner,
      timeout: 1
    )

    let snapshot = try bridge.fetchSnapshot()

    XCTAssertEqual(snapshot.overview.sessionCount, 2)
    XCTAssertEqual(runner.lastArguments, ["-m", "tokencat", "snapshot", "--since", "7d"])
  }

  func testFetchSnapshotReportsProcessFailure() {
    let runner = FakeRunner(result: ProcessResult(stdout: Data(), stderr: "boom", terminationStatus: 2))
    let bridge = TokenCatBridge(
      pythonURL: URL(fileURLWithPath: "/bin/echo"),
      repositoryRootURL: URL(fileURLWithPath: "/tmp"),
      runner: runner,
      timeout: 1
    )

    XCTAssertThrowsError(try bridge.fetchSnapshot()) { error in
      XCTAssertEqual(error as? TokenCatBridgeError, .processFailed(2, "boom"))
    }
  }
}

final class FakeRunner: TokenCatProcessRunning {
  let result: ProcessResult
  private(set) var lastArguments: [String] = []

  init(result: ProcessResult) {
    self.result = result
  }

  func run(
    executableURL: URL,
    arguments: [String],
    environment: [String: String],
    currentDirectoryURL: URL,
    timeout: TimeInterval
  ) throws -> ProcessResult {
    lastArguments = arguments
    return result
  }
}
