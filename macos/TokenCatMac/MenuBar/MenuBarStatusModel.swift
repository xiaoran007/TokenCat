import Foundation
import OSLog
import WidgetKit

@MainActor
final class MenuBarStatusModel: ObservableObject {
  @Published private(set) var snapshot: TokenCatSnapshot?
  @Published private(set) var isRefreshing = false
  @Published private(set) var errorMessage: String?

  private let bridge: TokenCatBridge
  private let store: SnapshotStore
  private let logger = Logger(subsystem: "com.xiaoran.tokencat.dev", category: "MenuBar")

  var menuBarSystemImage: String {
    if isRefreshing {
      return "arrow.triangle.2.circlepath"
    }
    if errorMessage != nil {
      return "exclamationmark.triangle"
    }
    return "chart.bar.xaxis"
  }

  init(bridge: TokenCatBridge, store: SnapshotStore) {
    self.bridge = bridge
    self.store = store
    loadCachedSnapshot()
  }

  static func live() -> MenuBarStatusModel {
    MenuBarStatusModel(bridge: .developmentDefault(), store: .developmentDefault())
  }

  func loadCachedSnapshot() {
    do {
      snapshot = try store.load()
      errorMessage = nil
      WidgetCenter.shared.reloadTimelines(ofKind: "TokenCatWidget")
      logger.info("Loaded cached snapshot generated at \(self.snapshot?.generatedAtDisplay ?? "unknown", privacy: .public)")
    } catch SnapshotStoreError.snapshotNotFound {
      snapshot = nil
      errorMessage = nil
      logger.info("No cached snapshot found")
    } catch {
      errorMessage = error.localizedDescription
      logger.error("Failed to load cached snapshot: \(error.localizedDescription, privacy: .public)")
    }
  }

  func refresh() {
    Task {
      await refreshNow()
    }
  }

  func refreshNow() async {
    isRefreshing = true
    errorMessage = nil
    logger.info("Starting TokenCat snapshot refresh")
    defer { isRefreshing = false }

    do {
      let bridge = self.bridge
      let refreshed = try await Task.detached(priority: .userInitiated) {
        try bridge.fetchSnapshot()
      }.value
      try store.save(refreshed)
      snapshot = refreshed
      WidgetCenter.shared.reloadTimelines(ofKind: "TokenCatWidget")
      WidgetCenter.shared.reloadAllTimelines()
      logger.info("Saved snapshot and requested widget timeline reload")
    } catch {
      errorMessage = error.localizedDescription
      logger.error("Snapshot refresh failed: \(error.localizedDescription, privacy: .public)")
    }
  }
}
