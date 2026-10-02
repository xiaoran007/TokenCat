import Foundation
import CTokenCat
import TokenCatKit

struct CoreFailure: Error, LocalizedError {
    let message: String
    var errorDescription: String? { message }
}

protocol UsageLoading: Sendable {
    func refresh(configuration: CoreConfiguration, queries: [CoreQuery]) async throws -> [Dashboard]
}

/// Owns the Rust handle on one queue. Scanning and querying never block the main actor.
final class CoreWorker: UsageLoading, @unchecked Sendable {
    private let queue = DispatchQueue(label: "com.tokencat.core", qos: .utility)
    private var handle: UnsafeMutableRawPointer?
    private var configuration: CoreConfiguration?

    func refresh(configuration: CoreConfiguration, queries: [CoreQuery]) async throws -> [Dashboard] {
        try await withCheckedThrowingContinuation { continuation in
            queue.async { [self] in
                do {
                    if handle == nil || self.configuration != configuration {
                        if let handle { tokencat_close(handle) }
                        handle = nil
                        self.configuration = nil
                        let encoder = JSONEncoder()
                        encoder.keyEncodingStrategy = .convertToSnakeCase
                        let configData = try encoder.encode(configuration)
                        let configString = String(decoding: configData, as: UTF8.self)
                        handle = configString.withCString { tokencat_open($0) }
                        guard handle != nil else {
                            let lastError = try takeString(tokencat_last_error())
                            let envelope = try CoreEnvelope<JSONValue>.decode(Data(lastError.utf8))
                            throw CoreFailure(message: envelope.error ?? "Native core returned no error detail")
                        }
                        self.configuration = configuration
                    }
                    let _: ScanReport = try unwrap(tokencat_scan(handle))
                    let encoder = JSONEncoder()
                    encoder.keyEncodingStrategy = .convertToSnakeCase
                    let snapshots: [Dashboard] = try queries.map { query in
                        let json = String(decoding: try encoder.encode(query), as: UTF8.self)
                        let snapshot: Dashboard = try json.withCString { try unwrap(tokencat_query(handle, $0)) }
                        guard snapshot.schemaVersion == 1 else { throw DashboardError.unsupportedSchema(snapshot.schemaVersion) }
                        return snapshot
                    }
                    continuation.resume(returning: snapshots)
                } catch { continuation.resume(throwing: error) }
            }
        }
    }

    private func takeString(_ pointer: UnsafeMutablePointer<CChar>?) throws -> String {
        guard let pointer else { throw CoreFailure(message: "Native core returned no result") }
        defer { tokencat_string_free(pointer) }
        return String(cString: pointer)
    }

    private func unwrap<Value: Decodable>(_ pointer: UnsafeMutablePointer<CChar>?) throws -> Value {
        let text = try takeString(pointer)
        let envelope = try CoreEnvelope<Value>.decode(Data(text.utf8))
        guard envelope.ok, let value = envelope.data else { throw CoreFailure(message: envelope.error ?? "Invalid native response") }
        return value
    }

    deinit {
        // The worker is retained by refresh closures until the queue has drained.
        if let handle { tokencat_close(handle) }
    }
}
