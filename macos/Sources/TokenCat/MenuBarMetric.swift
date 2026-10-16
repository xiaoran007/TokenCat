enum MenuBarMetric: String, CaseIterable, Identifiable {
    case cost
    case tokens

    var id: String { rawValue }
    var localizationKey: String { "settings.menuMetric.\(rawValue)" }
}
