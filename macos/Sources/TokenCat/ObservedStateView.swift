import SwiftUI
import TokenCatKit

extension JSONValue {
    subscript(_ key: String) -> JSONValue? {
        guard case .object(let object) = self else { return nil }
        return object[key]
    }
    var number: Double? { guard case .number(let number) = self else { return nil }; return number }
}

/// Quota values are explicitly observations, not a live entitlement query.
struct QuotaObservationView: View {
    let observation: ObservedState
    @EnvironmentObject private var settings: AppSettings
    var body: some View {
        let s = settings.strings
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Text(observation.provider.label + " " + s.text("quota.title")).font(.caption.weight(.semibold))
                Spacer()
                Text(s.relative(Date(milliseconds: observation.timestampMs))).font(.caption2).foregroundStyle(.secondary)
            }
            ForEach(["primary", "secondary"], id: \.self) { key in
                if let window = observation.data[key], let used = window["used_percent"]?.number {
                    VStack(alignment: .leading, spacing: 4) {
                        HStack {
                            if let minutes = window["window_minutes"]?.number {
                                Text(s.format("quota.window", Int(minutes)))
                            }
                            Spacer()
                            Text(s.percent(used / 100)).monospacedDigit()
                        }.font(.caption).foregroundStyle(.secondary)
                        ProgressView(value: min(100, max(0, used)), total: 100).tint(used >= 90 ? .orange : .accentColor)
                        if let reset = window["resets_at"]?.number {
                            Text(s.format("quota.resets", Date(timeIntervalSince1970: reset).formatted(.dateTime.month().day().hour().minute().locale(s.locale))))
                                .font(.caption2).foregroundStyle(.secondary)
                        }
                    }
                }
            }
            Text(s.text("quota.observed")).font(.caption2).foregroundStyle(.secondary)
        }
    }
}

struct ContextObservationView: View {
    let observation: ObservedState
    @EnvironmentObject private var settings: AppSettings
    var body: some View {
        let s = settings.strings
        if let window = observation.data["context_window"]?.number,
           let input = observation.data["last_input_tokens"]?.number, window > 0 {
            VStack(alignment: .leading, spacing: 8) {
                HStack {
                    Text(s.text("context.title")).font(.subheadline)
                    Spacer()
                    Text(s.percent(input / window)).monospacedDigit()
                }
                ProgressView(value: min(input, window), total: window)
                Text(s.format("context.observed", s.relative(Date(milliseconds: observation.timestampMs)))).font(.caption).foregroundStyle(.secondary)
            }
        }
    }
}
