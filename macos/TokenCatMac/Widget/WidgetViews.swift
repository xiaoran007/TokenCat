import SwiftUI
import WidgetKit

struct TokenCatWidgetView: View {
  @Environment(\.widgetFamily) private var family
  let entry: TokenCatWidgetEntry

  var body: some View {
    if let snapshot = entry.snapshot {
      content(snapshot)
        .containerBackground(.background, for: .widget)
    } else {
      VStack(alignment: .leading, spacing: 8) {
        Text("TokenCat")
          .font(.headline)
        Text("Open the menu bar app to refresh usage.")
          .font(.caption)
          .foregroundStyle(.secondary)
      }
      .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
      .containerBackground(.background, for: .widget)
    }
  }

  private func content(_ snapshot: TokenCatSnapshot) -> some View {
    VStack(alignment: .leading, spacing: family == .systemSmall ? 8 : 12) {
      HStack {
        Text("TokenCat")
          .font(.headline)
        Spacer()
        ProviderDots(providers: snapshot.providers)
      }

      Text(TokenCatFormat.tokens(snapshot.overview.tokenTotals.total))
        .font(.system(.largeTitle, design: .rounded).weight(.bold))
        .lineLimit(1)
        .minimumScaleFactor(0.7)

      HStack {
        Text(TokenCatFormat.cost(snapshot.overview.estimatedCost?.totalCost))
        Spacer()
        Text(snapshot.generatedAtDisplay)
      }
      .font(.caption)
      .foregroundStyle(.secondary)

      if family == .systemMedium {
        Divider()
        ForEach(snapshot.topModels.prefix(2)) { model in
          HStack {
            Text(model.model)
              .lineLimit(1)
            Spacer()
            Text(TokenCatFormat.tokens(model.tokenTotals.total))
              .foregroundStyle(.secondary)
          }
          .font(.caption)
        }
      }
    }
  }
}

private struct ProviderDots: View {
  let providers: [ProviderSnapshot]

  var body: some View {
    HStack(spacing: 4) {
      ForEach(providers.prefix(4)) { provider in
        Circle()
          .fill(provider.statusColor)
          .frame(width: 6, height: 6)
      }
    }
  }
}
