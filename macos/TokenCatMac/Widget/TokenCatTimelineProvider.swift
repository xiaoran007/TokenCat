import OSLog
import WidgetKit

private let logger = Logger(subsystem: "com.xiaoran.tokencat.dev", category: "Widget")

struct TokenCatWidgetEntry: TimelineEntry {
  let date: Date
  let snapshot: TokenCatSnapshot?
}

struct TokenCatTimelineProvider: TimelineProvider {
  let store: SnapshotStore

  init(store: SnapshotStore = .developmentDefault()) {
    self.store = store
  }

  func placeholder(in context: Context) -> TokenCatWidgetEntry {
    TokenCatWidgetEntry(date: Date(), snapshot: TokenCatSnapshot.placeholder)
  }

  func getSnapshot(in context: Context, completion: @escaping (TokenCatWidgetEntry) -> Void) {
    completion(TokenCatWidgetEntry(date: Date(), snapshot: loadSnapshot(reason: "snapshot")))
  }

  func getTimeline(in context: Context, completion: @escaping (Timeline<TokenCatWidgetEntry>) -> Void) {
    let snapshot = loadSnapshot(reason: "timeline")
    let entry = TokenCatWidgetEntry(date: Date(), snapshot: snapshot)
    let refreshMinutes = snapshot == nil ? 1 : 30
    let nextRefresh = Calendar.current.date(byAdding: .minute, value: refreshMinutes, to: Date()) ?? Date().addingTimeInterval(TimeInterval(refreshMinutes * 60))
    completion(Timeline(entries: [entry], policy: .after(nextRefresh)))
  }

  private func loadSnapshot(reason: String) -> TokenCatSnapshot? {
    do {
      let snapshot = try store.load()
      logger.info("Loaded widget snapshot for \(reason, privacy: .public)")
      return snapshot
    } catch {
      logger.error("Failed to load widget snapshot for \(reason, privacy: .public) in \(store.displayDirectoryPath, privacy: .public): \(error.localizedDescription, privacy: .public)")
      return nil
    }
  }
}

private extension SnapshotStore {
  var displayDirectoryPath: String {
    guard let path = directoryURL?.path else {
      return "unresolved"
    }
    return path.components(separatedBy: "/Library/Containers/").last ?? path
  }
}
