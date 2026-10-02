import Foundation

public struct CoreConfiguration: Codable, Equatable, Sendable {
    public let home: String
    public let databasePath: String
    public let codexRoot: String?
    public let claudeRoots: [String]
    public let pricingPath: String?
    public init(home: String, databasePath: String, codexRoot: String?, claudeRoots: [String], pricingPath: String?) {
        self.home = home; self.databasePath = databasePath; self.codexRoot = codexRoot
        self.claudeRoots = claudeRoots; self.pricingPath = pricingPath
    }
}

public struct CoreQuery: Codable, Sendable {
    public let sinceMs: Int64
    public let untilMs: Int64
    public let timezone: String
    public let showPaths: Bool
    public init(sinceMs: Int64, untilMs: Int64, timezone: String, showPaths: Bool) {
        self.sinceMs = sinceMs; self.untilMs = untilMs; self.timezone = timezone; self.showPaths = showPaths
    }
}

public struct CoreEnvelope<Value: Decodable>: Decodable {
    public let ok: Bool
    public let data: Value?
    public let error: String?
    public static func decode(_ data: Data) throws -> Self {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return try decoder.decode(Self.self, from: data)
    }
}
