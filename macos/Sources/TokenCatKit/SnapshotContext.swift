import Foundation

/// Captures the inputs that determine which data a snapshot is allowed to display.
public struct SnapshotContext: Equatable, Sendable {
    public let configuration: CoreConfiguration
    public let window: TimeWindow
    public let timeZone: TimeZone
    public let showPaths: Bool

    public init(configuration: CoreConfiguration, window: TimeWindow, timeZone: TimeZone, showPaths: Bool) {
        self.configuration = configuration
        self.window = window
        // Freeze an autoupdating system zone for the lifetime of this request.
        self.timeZone = TimeZone(identifier: timeZone.identifier)!
        self.showPaths = showPaths
    }

    public func queries(now: Date) -> [CoreQuery] {
        [.today, window].map { window in
            let interval = window.interval(now: now, timeZone: timeZone)
            return CoreQuery(sinceMs: interval.start.milliseconds, untilMs: interval.end.milliseconds,
                             timezone: timeZone.identifier, showPaths: showPaths)
        }
    }
}
