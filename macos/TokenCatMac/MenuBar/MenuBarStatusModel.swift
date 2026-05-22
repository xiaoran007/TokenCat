import Foundation
import WidgetKit

@MainActor
final class MenuBarStatusModel: ObservableObject {
  @Published private(set) var snapshot: TokenCatSnapshot?
  @Published private(set) var isRefreshing = false
  @Published private(set) var errorMessage: String?

  private let bridge: TokenCatBridge
  private let store: SnapshotStore

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
    MenuBarStatusModel(bridge: .developmentDefault(), store: .appGroupDefault())
  }

  func loadCachedSnapshot() {
    do {
      snapshot = try store.load()
      errorMessage = nil
    } catch SnapshotStoreError.snapshotNotFound {
      snapshot = nil
      errorMessage = nil
    } catch {
      errorMessage = error.localizedDescription
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
    defer { isRefreshing = false }

    do {
      let refreshed = try await Task.detached(priority: .userInitiated) {
        try bridge.fetchSnapshot()
      }.value
      try store.save(refreshed)
      snapshot = refreshed
      WidgetCenter.shared.reloadAllTimelines()
    } catch {
      errorMessage = error.localizedDescription
    }
  }
}
