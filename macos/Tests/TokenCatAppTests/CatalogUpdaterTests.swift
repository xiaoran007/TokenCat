import Foundation
import XCTest
@testable import TokenCat
@testable import TokenCatKit

private actor CatalogServer {
    var responses: [CatalogDownload]
    var requests: [URLRequest] = []
    init(_ responses: [CatalogDownload]) { self.responses = responses }
    func fetch(_ request: URLRequest) throws -> CatalogDownload {
        requests.append(request)
        guard !responses.isEmpty else { throw URLError(.notConnectedToInternet) }
        return responses.removeFirst()
    }
}

private final class CatalogClock: @unchecked Sendable {
    private let lock = NSLock()
    private var value = Date(timeIntervalSince1970: 1_780_000_000)
    func now() -> Date { lock.withLock { value } }
    func advance(_ seconds: TimeInterval) { lock.withLock { value.addTimeInterval(seconds) } }
}

@MainActor
final class CatalogUpdaterTests: XCTestCase {
    private func directory() throws -> URL {
        let path = FileManager.default.temporaryDirectory.appendingPathComponent("TokenCat.CatalogTests.\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: path, withIntermediateDirectories: true)
        addTeardownBlock { try FileManager.default.removeItem(at: path) }
        return path
    }

    private func response(_ rate: Double = 0.000002, etag: String = "version-1") -> CatalogDownload {
        let json = """
        {"gpt-test":{"litellm_provider":"openai","mode":"chat","input_cost_per_token":\(rate),
        "output_cost_per_token":0.00001,"cache_read_input_token_cost":0.0000002}}
        """
        return CatalogDownload(data: Data(json.utf8), statusCode: 200, etag: etag)
    }

    func testFirstUpdateSavesValidatedAtomicEnvelopeAndRestoresOffline() async throws {
        let path = try directory()
        let server = CatalogServer([response()])
        let clock = CatalogClock()
        let updater = CatalogUpdater(directory: path, fetch: { try await server.fetch($0) }, now: { clock.now() })
        XCTAssertNil(updater.activeURL)
        await updater.refreshIfDue(interval: 86400)
        XCTAssertNil(updater.state.error)
        XCTAssertNotNil(updater.state.revision)
        XCTAssertFalse(updater.state.updating)
        let saved = try Data(contentsOf: XCTUnwrap(updater.activeURL))
        let object = try XCTUnwrap(JSONSerialization.jsonObject(with: saved) as? [String: Any])
        XCTAssertEqual(object["tokencat_litellm_cache"] as? Int, 1)
        XCTAssertEqual(object["catalog"] as? String, String(data: response().data, encoding: .utf8))
        let restored = CatalogUpdater(directory: path, fetch: { _ in throw URLError(.notConnectedToInternet) }, now: { clock.now() })
        XCTAssertEqual(restored.state.revision, updater.state.revision)
        XCTAssertEqual(restored.state.retrievedAt, updater.state.retrievedAt)
        XCTAssertNil(restored.state.error)
    }

    func testScheduledChecksRespectIntervalAndManualRefreshRevalidatesETag() async throws {
        let server = CatalogServer([response(), CatalogDownload(data: Data(), statusCode: 304, etag: nil), response(0.000003, etag: "version-2")])
        let clock = CatalogClock()
        let updater = CatalogUpdater(directory: try directory(), fetch: { try await server.fetch($0) }, now: { clock.now() })
        await updater.refreshIfDue(interval: 86400)
        let firstRevision = updater.state.revision
        let downloaded = updater.state.retrievedAt
        clock.advance(3600)
        await updater.refreshIfDue(interval: 86400)
        var requests = await server.requests
        XCTAssertEqual(requests.count, 1)
        await updater.refresh()
        requests = await server.requests
        XCTAssertEqual(requests.count, 2)
        XCTAssertEqual(requests[1].value(forHTTPHeaderField: "If-None-Match"), "version-1")
        XCTAssertEqual(updater.state.retrievedAt, downloaded)
        XCTAssertEqual(updater.state.revision, firstRevision)
        clock.advance(86400)
        await updater.refreshIfDue(interval: 86400)
        XCTAssertNotEqual(updater.state.revision, firstRevision)
        XCTAssertEqual(updater.state.checkedAt, clock.now())
    }

    func testMalformedDownloadAndHTTPFailureNeverReplaceSelectedSnapshot() async throws {
        let server = CatalogServer([response(), CatalogDownload(data: Data("{\"bad\":{}}".utf8), statusCode: 200, etag: "bad"),
                                    CatalogDownload(data: Data(), statusCode: 503, etag: nil)])
        let updater = CatalogUpdater(directory: try directory(), fetch: { try await server.fetch($0) })
        await updater.refresh()
        let previous = try Data(contentsOf: XCTUnwrap(updater.activeURL))
        let revision = updater.state.revision
        for _ in 0..<2 {
            await updater.refresh()
            XCTAssertNotNil(updater.state.error)
            XCTAssertEqual(updater.state.revision, revision)
            XCTAssertEqual(try Data(contentsOf: updater.cacheURL), previous)
            XCTAssertFalse(updater.state.updating)
        }
    }

    func testFailedAutomaticCheckIsThrottledButManualRetryRemainsAvailable() async throws {
        let server = CatalogServer([])
        let clock = CatalogClock()
        let updater = CatalogUpdater(directory: try directory(), fetch: { try await server.fetch($0) }, now: { clock.now() })
        await updater.refreshIfDue(interval: 86400)
        await updater.refreshIfDue(interval: 86400)
        var requests = await server.requests
        XCTAssertEqual(requests.count, 1)
        XCTAssertNotNil(updater.state.error)
        XCTAssertNil(updater.activeURL)
        await updater.refresh()
        requests = await server.requests
        XCTAssertEqual(requests.count, 2)
        clock.advance(600)
        await updater.refreshIfDue(interval: 86400)
        requests = await server.requests
        XCTAssertEqual(requests.count, 3)
    }

    func testNotModifiedWithoutCachedCatalogDoesNotPretendToSucceed() async throws {
        let server = CatalogServer([CatalogDownload(data: Data(), statusCode: 304, etag: nil)])
        let updater = CatalogUpdater(directory: try directory(), fetch: { try await server.fetch($0) })
        await updater.refresh()
        XCTAssertNotNil(updater.state.error)
        XCTAssertNil(updater.activeURL)
        XCTAssertNil(updater.state.checkedAt)
    }

    func testSavedCatalogAndRawSnapshotHaveSameIdentity() throws {
        let raw = response().data
        let date = Date()
        let identity = try CatalogValidation.validate(raw, at: date)
        let envelope = try JSONSerialization.data(withJSONObject: [
            "tokencat_litellm_cache": 1, "catalog": String(decoding: raw, as: UTF8.self),
            "retrieved_at": date.ISO8601Format(), "checked_at": date.ISO8601Format(), "catalog_id": identity.id
        ])
        XCTAssertEqual(try CatalogValidation.validate(envelope, at: date).id, identity.id)
    }

    func testAppHonorsOfflineAndCustomCatalogPreferences() async throws {
        let suite = "TokenCat.CatalogPreferences.\(UUID().uuidString)"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        let settings = AppSettings(defaults: defaults)
        settings.home = NSTemporaryDirectory()
        let server = CatalogServer([response()])
        let updater = CatalogUpdater(directory: try directory(), fetch: { try await server.fetch($0) })
        let model = AppModel(settings: settings, worker: FixtureUsageLoader(result: .success(MenuFixtures.dashboard())), catalogUpdater: updater)
        XCTAssertTrue(settings.autoUpdateCatalog)
        XCTAssertEqual(settings.catalogUpdateHours, 24)
        settings.autoUpdateCatalog = false
        await model.checkCatalogUpdate()
        settings.autoUpdateCatalog = true
        settings.pricingPath = "/custom/pricing.json"
        await model.checkCatalogUpdate()
        var requests = await server.requests
        XCTAssertTrue(requests.isEmpty)
        settings.pricingPath = ""
        await model.checkCatalogUpdate()
        requests = await server.requests
        XCTAssertEqual(requests.count, 1)
        XCTAssertNotNil(updater.state.revision)
    }

    func testNewSnapshotAtSamePathRepricesExistingLedgerWithoutDuplicatingUsage() async throws {
        let root = try directory()
        let projects = root.appendingPathComponent(".claude/projects/test")
        try FileManager.default.createDirectory(at: projects, withIntermediateDirectories: true)
        let usage = #"{"type":"assistant","sessionId":"s","timestamp":"2026-10-02T12:00:00Z","message":{"id":"m","role":"assistant","model":"gpt-test","usage":{"input_tokens":100,"cache_read_input_tokens":0,"cache_creation_input_tokens":0,"output_tokens":0}}}"# + "\n"
        try Data(usage.utf8).write(to: projects.appendingPathComponent("usage.jsonl"))
        let server = CatalogServer([response(), response(0.000004, etag: "v2")])
        let updater = CatalogUpdater(directory: root.appendingPathComponent("pricing"), fetch: { try await server.fetch($0) })
        let worker = CoreWorker()
        let query = CoreQuery(sinceMs: 1_790_899_200_000, untilMs: 1_790_985_600_000, timezone: "UTC", showPaths: false)
        func config() -> CoreConfiguration {
            CoreConfiguration(home: root.path, databasePath: root.appendingPathComponent("ledger.sqlite").path,
                codexRoot: nil, claudeRoots: [], pricingPath: updater.activeURL?.path,
                pricingRevision: updater.state.revision)
        }
        await updater.refresh()
        let firstConfig = config()
        let first = try await worker.refresh(configuration: firstConfig, queries: [query])[0]
        XCTAssertEqual(first.summary.cost.minUsd, 0.0002, accuracy: 0.000000001)
        await updater.refresh()
        let secondConfig = config()
        let second = try await worker.refresh(configuration: secondConfig, queries: [query])[0]
        XCTAssertEqual(firstConfig.pricingPath, secondConfig.pricingPath)
        XCTAssertNotEqual(firstConfig.pricingRevision, secondConfig.pricingRevision)
        XCTAssertEqual(second.summary.cost.minUsd, 0.0004, accuracy: 0.000000001)
        XCTAssertEqual(second.summary.eventCount, 1)
        XCTAssertEqual(second.lastScan?.eventsUpserted, 0)
        XCTAssertEqual(second.summary.cost.pricingMatches?.first?.source, "openai")
    }
}
