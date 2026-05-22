import Foundation

enum SnapshotStoreError: LocalizedError, Equatable {
  case missingAppGroupIdentifier
  case missingAppGroupContainer(String)
  case snapshotNotFound

  var errorDescription: String? {
    switch self {
    case .missingAppGroupIdentifier:
      return "TokenCat app group identifier is not configured."
    case .missingAppGroupContainer(let identifier):
      return "TokenCat app group container is unavailable: \(identifier)"
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
