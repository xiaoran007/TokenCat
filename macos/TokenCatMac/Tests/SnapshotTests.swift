import XCTest
@testable import TokenCatMac

final class SnapshotTests: XCTestCase {
  func testDecodesSnapshotJSON() throws {
    let data = Data(Self.sampleSnapshot.utf8)
    let snapshot = try JSONDecoder.tokenCatSnapshotDecoder.decode(TokenCatSnapshot.self, from: data)

    XCTAssertEqual(snapshot.schemaVersion, 1)
    XCTAssertEqual(snapshot.overview.sessionCount, 2)
    XCTAssertEqual(snapshot.overview.tokenTotals.total, 1800)
    XCTAssertEqual(snapshot.providers.first?.displayName, "Codex")
    XCTAssertEqual(snapshot.topModels.first?.id, "codex:gpt-5")
  }

  static let sampleSnapshot = """
  {
    "schema_version": 1,
    "generated_at": "2026-05-22T12:00:00Z",
    "providers": [
      {"provider": "codex", "status": "supported", "reasons": [], "warnings": []}
    ],
    "overview": {
      "session_count": 2,
      "model_count": 1,
      "token_totals": {"input": 1000, "output": 500, "cached": 200, "reasoning": 100, "tool": 0, "total": 1800},
      "estimated_cost": {"input_cost": 0.1, "cached_input_cost": 0.01, "output_cost": 0.2, "total_cost": 0.31, "currency": "USD"},
      "secondary_metrics": {"priced_coverage": 1.0, "provider_count": 1}
    },
    "usage": {"granularity": "daily", "records": []},
    "top_models": [
      {"provider": "codex", "model": "gpt-5", "session_count": 2, "message_count": 4, "token_totals": {"input": 1000, "output": 500, "cached": 200, "reasoning": 100, "tool": 0, "total": 1800}, "estimated_cost": null, "priced_token_coverage": 1.0}
    ],
    "pricing": {"catalog": null, "coverage": null},
    "warnings": []
  }
  """
}
