import AppKit
import SwiftUI

struct MenuBarPopoverView: View {
  @ObservedObject var model: MenuBarStatusModel

  var body: some View {
    VStack(alignment: .leading, spacing: 16) {
      header

      if let snapshot = model.snapshot {
        SnapshotSummaryView(snapshot: snapshot)
        ProviderStatusView(providers: snapshot.providers)
        TopModelsView(models: snapshot.topModels)
      } else {
        ContentUnavailableView("No Snapshot", systemImage: "chart.bar.doc.horizontal", description: Text("Refresh TokenCat to create the first local usage snapshot."))
          .frame(width: 360, height: 180)
      }

      if let errorMessage = model.errorMessage {
        Text(errorMessage)
          .font(.caption)
          .foregroundStyle(.red)
          .lineLimit(3)
      }

      footer
    }
    .padding(18)
    .frame(width: 380)
    .task {
      if model.snapshot == nil {
        await model.refreshNow()
      }
    }
  }

  private var header: some View {
    HStack {
      VStack(alignment: .leading, spacing: 2) {
        Text("TokenCat")
          .font(.headline)
        Text(model.snapshot.map { "Updated \($0.generatedAtDisplay)" } ?? "Development snapshot")
          .font(.caption)
          .foregroundStyle(.secondary)
      }

      Spacer()

      Button {
        model.refresh()
      } label: {
        Image(systemName: "arrow.clockwise")
      }
      .disabled(model.isRefreshing)
      .help("Refresh TokenCat usage")
    }
  }

  private var footer: some View {
    HStack {
      if model.isRefreshing {
        ProgressView()
          .controlSize(.small)
        Text("Refreshing")
          .font(.caption)
          .foregroundStyle(.secondary)
      }

      Spacer()

      Button("Quit") {
        NSApplication.shared.terminate(nil)
      }
      .keyboardShortcut("q")
    }
  }
}

private struct SnapshotSummaryView: View {
  let snapshot: TokenCatSnapshot

  var body: some View {
    Grid(alignment: .leading, horizontalSpacing: 20, verticalSpacing: 8) {
      GridRow {
        MetricCell(title: "Sessions", value: "\(snapshot.overview.sessionCount)")
        MetricCell(title: "Tokens", value: TokenCatFormat.tokens(snapshot.overview.tokenTotals.total))
        MetricCell(title: "Cost", value: TokenCatFormat.cost(snapshot.overview.estimatedCost?.totalCost))
      }

      GridRow {
        MetricCell(title: "Models", value: "\(snapshot.overview.modelCount)")
        MetricCell(title: "Coverage", value: TokenCatFormat.percent(snapshot.overview.secondaryMetrics?.pricedCoverage))
        MetricCell(title: "Window", value: snapshot.usage.granularity.capitalized)
      }
    }
  }
}

private struct MetricCell: View {
  let title: String
  let value: String

  var body: some View {
    VStack(alignment: .leading, spacing: 2) {
      Text(title)
        .font(.caption)
        .foregroundStyle(.secondary)
      Text(value)
        .font(.system(.title3, design: .rounded).weight(.semibold))
        .lineLimit(1)
        .minimumScaleFactor(0.75)
    }
    .frame(width: 104, alignment: .leading)
  }
}

private struct ProviderStatusView: View {
  let providers: [ProviderSnapshot]

  var body: some View {
    VStack(alignment: .leading, spacing: 8) {
      Text("Providers")
        .font(.subheadline.weight(.semibold))

      ForEach(providers) { provider in
        HStack(spacing: 8) {
          Circle()
            .fill(provider.statusColor)
            .frame(width: 8, height: 8)
          Text(provider.displayName)
            .lineLimit(1)
          Spacer()
          Text(provider.status)
            .font(.caption)
            .foregroundStyle(.secondary)
        }
      }
    }
  }
}

private struct TopModelsView: View {
  let models: [TopModelSnapshot]

  var body: some View {
    VStack(alignment: .leading, spacing: 8) {
      Text("Top Models")
        .font(.subheadline.weight(.semibold))

      ForEach(models.prefix(4)) { model in
        HStack {
          Text(model.model)
            .lineLimit(1)
          Spacer()
          Text(TokenCatFormat.tokens(model.tokenTotals.total))
            .foregroundStyle(.secondary)
        }
        .font(.callout)
      }
    }
  }
}
