import Foundation
import Combine
import CTokenCat
import TokenCatKit

struct CatalogIdentity: Decodable, Sendable {
    let id: String
    let modelCount: Int
}

struct CatalogDownload: Sendable {
    let data: Data
    let statusCode: Int
    let etag: String?
}

struct CatalogUpdateState: Equatable {
    var updating = false
    var hasCache = false
    var revision: String?
    var checkedAt: Date?
    var retrievedAt: Date?
    var error: String?
}

enum CatalogValidation {
    static func validate(_ data: Data, at date: Date) throws -> CatalogIdentity {
        guard let json = String(data: data, encoding: .utf8), !json.contains("\0") else {
            throw CoreFailure(message: "The price catalog is not valid UTF-8 JSON.")
        }
        let pointer = json.withCString { text in
            date.ISO8601Format().withCString { timestamp in tokencat_validate_catalog(text, timestamp) }
        }
        guard let pointer else { throw CoreFailure(message: "Could not validate the price catalog.") }
        defer { tokencat_string_free(pointer) }
        let envelope = try CoreEnvelope<CatalogIdentity>.decode(Data(String(cString: pointer).utf8))
        guard envelope.ok, let identity = envelope.data else {
            throw CoreFailure(message: envelope.error ?? "Invalid price catalog.")
        }
        return identity
    }
}

/// A single atomic envelope keeps the downloaded snapshot, ETag and timestamps
/// together. Failed updates leave the currently selected snapshot untouched.
@MainActor
final class CatalogUpdater: ObservableObject {
    static let source = URL(string: "https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json")!
    @Published private(set) var state = CatalogUpdateState()
    let cacheURL: URL
    private var etag: String?
    private var lastAttempt: Date?
    private let fetch: @Sendable (URLRequest) async throws -> CatalogDownload
    private let validate: @Sendable (Data, Date) throws -> CatalogIdentity
    private let now: @Sendable () -> Date

    init(directory: URL,
         fetch: @escaping @Sendable (URLRequest) async throws -> CatalogDownload = { try await CatalogUpdater.download($0) },
         validate: @escaping @Sendable (Data, Date) throws -> CatalogIdentity = { try CatalogValidation.validate($0, at: $1) },
         now: @escaping @Sendable () -> Date = { Date() }) {
        cacheURL = directory.appendingPathComponent("litellm-cache.json")
        self.fetch = fetch; self.validate = validate; self.now = now
        if FileManager.default.fileExists(atPath: cacheURL.path) {
            state.hasCache = true
            do {
                let saved = try Self.readEnvelope(cacheURL)
                let retrieved = try Self.date(saved, key: "retrieved_at")
                let identity = try validate(Data(contentsOf: cacheURL), retrieved)
                state.revision = identity.id
                state.retrievedAt = retrieved
                state.checkedAt = try Self.date(saved, key: "checked_at")
                etag = saved["etag"] as? String
            } catch {
                // Keep the chosen path visible as an error; never silently swap
                // a damaged saved catalog for a different set of prices.
                state.error = error.localizedDescription
            }
        }
    }

    var activeURL: URL? { state.hasCache ? cacheURL : nil }

    func refreshIfDue(interval: TimeInterval) async {
        let date = now()
        guard state.checkedAt.map({ date.timeIntervalSince($0) >= interval }) ?? true else { return }
        // Usage refreshes run frequently. A failed network check retries at most
        // every ten minutes; a user's explicit refresh is always available.
        guard lastAttempt.map({ date.timeIntervalSince($0) >= 600 }) ?? true else { return }
        await refresh()
    }

    func refresh() async {
        guard !state.updating else { return }
        state.updating = true
        state.error = nil
        lastAttempt = now()
        defer { state.updating = false }
        do {
            var request = URLRequest(url: Self.source, cachePolicy: .reloadIgnoringLocalCacheData, timeoutInterval: 30)
            request.setValue("application/json", forHTTPHeaderField: "Accept")
            if let etag { request.setValue(etag, forHTTPHeaderField: "If-None-Match") }
            let response = try await fetch(request)
            let checked = now()
            var envelope: [String: Any]
            let identity: CatalogIdentity
            if response.statusCode == 304 {
                guard state.hasCache, let revision = state.revision else {
                    throw CoreFailure(message: "The server returned no catalog and no valid local snapshot is available.")
                }
                envelope = try Self.readEnvelope(cacheURL)
                identity = CatalogIdentity(id: revision, modelCount: 0)
            } else {
                guard response.statusCode == 200 else {
                    throw CoreFailure(message: "Price update returned HTTP \(response.statusCode).")
                }
                guard response.data.count <= 30 * 1024 * 1024 else {
                    throw CoreFailure(message: "The downloaded price catalog is too large.")
                }
                let validate = self.validate
                identity = try await Task.detached { try validate(response.data, checked) }.value
                // Preserve source numeric literals. Foundation's JSON round trip
                // can change floating-point rates and the snapshot identity.
                guard let catalog = String(data: response.data, encoding: .utf8) else {
                    throw CoreFailure(message: "Invalid LiteLLM catalog.")
                }
                envelope = ["tokencat_litellm_cache": 1, "catalog": catalog,
                            "catalog_id": identity.id, "retrieved_at": checked.ISO8601Format(),
                            "source": Self.source.absoluteString]
            }
            envelope["checked_at"] = checked.ISO8601Format()
            let newETag = response.statusCode == 304 ? (response.etag ?? etag) : response.etag
            envelope["etag"] = newETag
            let encoded = try JSONSerialization.data(withJSONObject: envelope, options: [.sortedKeys])
            try FileManager.default.createDirectory(at: cacheURL.deletingLastPathComponent(), withIntermediateDirectories: true)
            try encoded.write(to: cacheURL, options: .atomic)
            etag = newETag
            state.hasCache = true
            state.revision = identity.id
            state.checkedAt = checked
            state.retrievedAt = try Self.date(envelope, key: "retrieved_at")
        } catch {
            state.error = error.localizedDescription
        }
    }

    nonisolated private static func download(_ request: URLRequest) async throws -> CatalogDownload {
        let (data, response) = try await URLSession.shared.data(for: request)
        guard let response = response as? HTTPURLResponse else {
            throw CoreFailure(message: "The price server returned an invalid response.")
        }
        return CatalogDownload(data: data, statusCode: response.statusCode,
                               etag: response.value(forHTTPHeaderField: "ETag"))
    }

    private static func readEnvelope(_ url: URL) throws -> [String: Any] {
        guard let saved = try JSONSerialization.jsonObject(with: Data(contentsOf: url)) as? [String: Any],
              saved["tokencat_litellm_cache"] as? Int == 1,
              saved["catalog"] is String else {
            throw CoreFailure(message: "The saved price catalog is invalid.")
        }
        return saved
    }

    private static func date(_ object: [String: Any], key: String) throws -> Date {
        guard let value = object[key] as? String else {
            throw CoreFailure(message: "The price catalog has no \(key) timestamp.")
        }
        return try Date.ISO8601FormatStyle().parse(value)
    }
}
