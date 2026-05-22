import WidgetKit

struct TokenCatWidgetEntry: TimelineEntry {
  let date: Date
  let snapshot: TokenCatSnapshot?
}

struct TokenCatTimelineProvider: TimelineProvider {
  let store: SnapshotStore

  init(store: SnapshotStore = .appGroupDefault()) {
    self.store = store
  }

  func placeholder(in context: Context) -> TokenCatWidgetEntry {
    TokenCatWidgetEntry(date: Date(), snapshot: TokenCatSnapshot.placeholder)
  }

  func getSnapshot(in context: Context, completion: @escaping (TokenCatWidgetEntry) -> Void) {
    completion(TokenCatWidgetEntry(date: Date(), snapshot: try? store.load()))
  }

  func getTimeline(in context: Context, completion: @escaping (Timeline<TokenCatWidgetEntry>) -> Void) {
    let entry = TokenCatWidgetEntry(date: Date(), snapshot: try? store.load())
    let nextRefresh = Calendar.current.date(byAdding: .minute, value: 30, to: Date()) ?? Date().addingTimeInterval(1800)
    completion(Timeline(entries: [entry], policy: .after(nextRefresh)))
  }
}
