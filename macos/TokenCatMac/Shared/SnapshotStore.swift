import Foundation

enum SnapshotStoreError: LocalizedError, Equatable {
  case missingAppGroupIdentifier
  case missingAppGroupContainer(String)
  case missingWidgetBundleIdentifier
  case missingApplicationSupportDirectory
  case snapshotNotFound

  var errorDescription: String? {
    switch self {
    case .missingAppGroupIdentifier:
      return "TokenCat app group identifier is not configured."
    case .missingAppGroupContainer(let identifier):
      return "TokenCat app group container is unavailable: \(identifier)"
    case .missingWidgetBundleIdentifier:
      return "TokenCat widget bundle identifier is not configured."
    case .missingApplicationSupportDirectory:
      return "TokenCat application support directory is unavailable."
    case .snapshotNotFound:
      return "TokenCat snapshot has not been created yet."
    }
  }
}

struct SnapshotStore {
  let directoryURL: URL?
  let fileName: String
  let resolutionError: SnapshotStoreError?

  init(directoryURL: URL, fileName: String = "snapshot.json") {
    self.directoryURL = directoryURL
    self.fileName = fileName
    self.resolutionError = nil
  }

  private init(error: SnapshotStoreError, fileName: String = "snapshot.json") {
    self.directoryURL = nil
    self.fileName = fileName
    self.resolutionError = error
  }

  static func appGroupDefault(bundle: Bundle = .main) -> SnapshotStore {
    guard let identifier = bundle.object(forInfoDictionaryKey: "TokenCatAppGroupIdentifier") as? String,
          !identifier.isEmpty else {
      return SnapshotStore(error: .missingAppGroupIdentifier)
    }

    guard let container = FileManager.default.containerURL(forSecurityApplicationGroupIdentifier: identifier) else {
      return SnapshotStore(error: .missingAppGroupContainer(identifier))
    }

    return SnapshotStore(directoryURL: container)
  }

  static func developmentDefault(bundle: Bundle = .main, fileManager: FileManager = .default) -> SnapshotStore {
    if bundle.bundlePath.hasSuffix(".appex") {
      guard let applicationSupportURL = fileManager.urls(for: .applicationSupportDirectory, in: .userDomainMask).first else {
        return SnapshotStore(error: .missingApplicationSupportDirectory)
      }
      return SnapshotStore(directoryURL: applicationSupportURL.appendingPathComponent("TokenCat", isDirectory: true))
    }

    let widgetBundleIdentifier = bundle.object(forInfoDictionaryKey: "TokenCatWidgetBundleIdentifier") as? String
    guard let widgetBundleIdentifier, !widgetBundleIdentifier.isEmpty else {
      return SnapshotStore(error: .missingWidgetBundleIdentifier)
    }

    let directoryURL = fileManager.homeDirectoryForCurrentUser
      .appendingPathComponent("Library", isDirectory: true)
      .appendingPathComponent("Containers", isDirectory: true)
      .appendingPathComponent(widgetBundleIdentifier, isDirectory: true)
      .appendingPathComponent("Data", isDirectory: true)
      .appendingPathComponent("Library", isDirectory: true)
      .appendingPathComponent("Application Support", isDirectory: true)
      .appendingPathComponent("TokenCat", isDirectory: true)

    return SnapshotStore(directoryURL: directoryURL)
  }

  func load() throws -> TokenCatSnapshot {
    let snapshotURL = try snapshotFileURL()
    guard FileManager.default.fileExists(atPath: snapshotURL.path) else {
      throw SnapshotStoreError.snapshotNotFound
    }
    let data = try Data(contentsOf: snapshotURL)
    return try JSONDecoder.tokenCatSnapshotDecoder.decode(TokenCatSnapshot.self, from: data)
  }

  func save(_ snapshot: TokenCatSnapshot) throws {
    guard let directoryURL else {
      throw resolutionError ?? SnapshotStoreError.missingAppGroupIdentifier
    }
    try FileManager.default.createDirectory(at: directoryURL, withIntermediateDirectories: true)
    let data = try JSONEncoder.tokenCatSnapshotEncoder.encode(snapshot)
    let temporaryURL = directoryURL.appendingPathComponent(".\(fileName).tmp")
    try data.write(to: temporaryURL, options: .atomic)
    let snapshotURL = try snapshotFileURL()
    if FileManager.default.fileExists(atPath: snapshotURL.path) {
      _ = try FileManager.default.replaceItemAt(snapshotURL, withItemAt: temporaryURL)
    } else {
      try FileManager.default.moveItem(at: temporaryURL, to: snapshotURL)
    }
  }

  private func snapshotFileURL() throws -> URL {
    guard let directoryURL else {
      throw resolutionError ?? SnapshotStoreError.missingAppGroupIdentifier
    }
    return directoryURL.appendingPathComponent(fileName)
  }
}
