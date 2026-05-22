import SwiftUI
import WidgetKit

struct TokenCatWidget: Widget {
  let kind = "TokenCatWidget"

  var body: some WidgetConfiguration {
    StaticConfiguration(kind: kind, provider: TokenCatTimelineProvider()) { entry in
      TokenCatWidgetView(entry: entry)
    }
    .configurationDisplayName("TokenCat")
    .description("Local AI coding agent usage at a glance.")
    .supportedFamilies([.systemSmall, .systemMedium])
  }
}
