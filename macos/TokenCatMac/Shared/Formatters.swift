import Foundation

enum TokenCatFormat {
  static func tokens(_ value: Int?) -> String {
    let number = Double(value ?? 0)
    let absolute = abs(number)
    if absolute >= 1_000_000_000 {
      return String(format: "%.1fB", number / 1_000_000_000)
    }
    if absolute >= 1_000_000 {
      return String(format: "%.1fM", number / 1_000_000)
    }
    if absolute >= 1_000 {
      return String(format: "%.1fK", number / 1_000)
    }
    return String(Int(number))
  }

  static func cost(_ value: Double?) -> String {
    String(format: "$%.2f", value ?? 0)
  }

  static func percent(_ value: Double?) -> String {
    String(format: "%.0f%%", (value ?? 0) * 100)
  }

  static func relativeDate(_ date: Date) -> String {
    let formatter = RelativeDateTimeFormatter()
    formatter.unitsStyle = .abbreviated
    return formatter.localizedString(for: date, relativeTo: Date())
  }
}
