import Foundation
import SwiftUI

struct TokenCatSnapshot: Codable, Equatable {
  let schemaVersion: Int
  let generatedAt: Date
  let providers: [ProviderSnapshot]
  let overview: OverviewSnapshot
  let usage: UsageSnapshot
  let topModels: [TopModelSnapshot]
  let pricing: PricingSnapshot
  let warnings: [String]

  enum CodingKeys: String, CodingKey {
    case schemaVersion = "schema_version"
    case generatedAt = "generated_at"
    case providers
    case overview
    case usage
    case topModels = "top_models"
    case pricing
    case warnings
  }

  var generatedAtDisplay: String {
    TokenCatFormat.relativeDate(generatedAt)
  }
}

struct ProviderSnapshot: Codable, Equatable, Identifiable {
  let provider: String
  let status: String
  let reasons: [String]
  let warnings: [String]

  var id: String { provider }

  var displayName: String {
    switch provider {
    case "codex":
      return "Codex"
    case "claude":
      return "Claude Code"
    case "gemini":
      return "Gemini CLI"
    case "copilot":
      return "GitHub Copilot"
    default:
      return provider
    }
  }

  var statusColor: Color {
    switch status {
    case "supported":
      return .green
    case "partial":
      return .yellow
    case "not_found":
      return .secondary
    default:
      return .red
    }
  }
}

struct OverviewSnapshot: Codable, Equatable {
  let sessionCount: Int
  let modelCount: Int
  let tokenTotals: TokenTotalsSnapshot
  let estimatedCost: CostSnapshot?
  let secondaryMetrics: SecondaryMetricsSnapshot?

  enum CodingKeys: String, CodingKey {
    case sessionCount = "session_count"
    case modelCount = "model_count"
    case tokenTotals = "token_totals"
    case estimatedCost = "estimated_cost"
    case secondaryMetrics = "secondary_metrics"
  }
}

struct SecondaryMetricsSnapshot: Codable, Equatable {
  let pricedCoverage: Double?
  let providerCount: Int?

  enum CodingKeys: String, CodingKey {
    case pricedCoverage = "priced_coverage"
    case providerCount = "provider_count"
  }
}

struct UsageSnapshot: Codable, Equatable {
  let granularity: String
  let records: [UsageRecordSnapshot]
}

struct UsageRecordSnapshot: Codable, Equatable, Identifiable {
  let date: String
  let label: String
  let providers: [String]
  let sessionCount: Int
  let tokenTotals: TokenTotalsSnapshot
  let estimatedCost: CostSnapshot?
  let pricedRatio: Double?
  let models: [TopModelSnapshot]

  var id: String { label }

  enum CodingKeys: String, CodingKey {
    case date
    case label
    case providers
    case sessionCount = "session_count"
    case tokenTotals = "token_totals"
    case estimatedCost = "estimated_cost"
    case pricedRatio = "priced_ratio"
    case models
  }
}

struct TopModelSnapshot: Codable, Equatable, Identifiable {
  let provider: String
  let model: String
  let sessionCount: Int?
  let messageCount: Int?
  let tokenTotals: TokenTotalsSnapshot
  let estimatedCost: CostSnapshot?
  let pricedTokenCoverage: Double?

  var id: String { "\(provider):\(model)" }

  enum CodingKeys: String, CodingKey {
    case provider
    case model
    case sessionCount = "session_count"
    case messageCount = "message_count"
    case tokenTotals = "token_totals"
    case estimatedCost = "estimated_cost"
    case pricedTokenCoverage = "priced_token_coverage"
  }
}

struct TokenTotalsSnapshot: Codable, Equatable {
  let input: Int?
  let output: Int?
  let cached: Int?
  let reasoning: Int?
  let tool: Int?
  let total: Int?
}

struct CostSnapshot: Codable, Equatable {
  let inputCost: Double?
  let cachedInputCost: Double?
  let outputCost: Double?
  let totalCost: Double?
  let currency: String?

  enum CodingKeys: String, CodingKey {
    case inputCost = "input_cost"
    case cachedInputCost = "cached_input_cost"
    case outputCost = "output_cost"
    case totalCost = "total_cost"
    case currency
  }
}

struct PricingSnapshot: Codable, Equatable {
  let catalog: PricingCatalogSnapshot?
  let coverage: PricingCoverageSnapshot?
}

struct PricingCatalogSnapshot: Codable, Equatable {
  let source: String
  let loadedAt: Date?
  let sourceURL: String?
  let refreshedAt: String?
  let modelCount: Int

  enum CodingKeys: String, CodingKey {
    case source
    case loadedAt = "loaded_at"
    case sourceURL = "source_url"
    case refreshedAt = "refreshed_at"
    case modelCount = "model_count"
  }
}

struct PricingCoverageSnapshot: Codable, Equatable {
  let totalTokens: Int
  let pricedTokens: Int
  let pricedRatio: Double
  let unknownModels: [String]
  let estimatedCost: CostSnapshot?

  enum CodingKeys: String, CodingKey {
    case totalTokens = "total_tokens"
    case pricedTokens = "priced_tokens"
    case pricedRatio = "priced_ratio"
    case unknownModels = "unknown_models"
    case estimatedCost = "estimated_cost"
  }
}

extension TokenCatSnapshot {
  static var placeholder: TokenCatSnapshot {
    TokenCatSnapshot(
      schemaVersion: 1,
      generatedAt: Date(),
      providers: [
        ProviderSnapshot(provider: "codex", status: "supported", reasons: [], warnings: []),
        ProviderSnapshot(provider: "claude", status: "partial", reasons: [], warnings: [])
      ],
      overview: OverviewSnapshot(
        sessionCount: 12,
        modelCount: 4,
        tokenTotals: TokenTotalsSnapshot(input: 120000, output: 34000, cached: 40000, reasoning: 6000, tool: 0, total: 200000),
        estimatedCost: CostSnapshot(inputCost: 0.15, cachedInputCost: 0.01, outputCost: 0.24, totalCost: 0.40, currency: "USD"),
        secondaryMetrics: SecondaryMetricsSnapshot(pricedCoverage: 0.92, providerCount: 2)
      ),
      usage: UsageSnapshot(granularity: "daily", records: []),
      topModels: [
        TopModelSnapshot(provider: "codex", model: "gpt-5", sessionCount: 8, messageCount: 30, tokenTotals: TokenTotalsSnapshot(input: nil, output: nil, cached: nil, reasoning: nil, tool: nil, total: 130000), estimatedCost: nil, pricedTokenCoverage: nil)
      ],
      pricing: PricingSnapshot(catalog: nil, coverage: nil),
      warnings: []
    )
  }
}

extension JSONDecoder {
  static var tokenCatSnapshotDecoder: JSONDecoder {
    let decoder = JSONDecoder()
    decoder.dateDecodingStrategy = .iso8601
    return decoder
  }
}

extension JSONEncoder {
  static var tokenCatSnapshotEncoder: JSONEncoder {
    let encoder = JSONEncoder()
    encoder.dateEncodingStrategy = .iso8601
    encoder.outputFormatting = [.sortedKeys, .prettyPrinted]
    return encoder
  }
}
