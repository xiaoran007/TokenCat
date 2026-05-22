import Foundation

enum TokenCatBridgeError: LocalizedError, Equatable {
  case missingEnvironment(String)
  case invalidPythonPath(String)
  case processFailed(Int32, String)
  case timedOut(TimeInterval)

  var errorDescription: String? {
    switch self {
    case .missingEnvironment(let name):
      return "Missing required development environment variable: \(name)"
    case .invalidPythonPath(let path):
      return "TokenCat Python executable does not exist: \(path)"
    case .processFailed(let code, let stderr):
      return "tokencat snapshot failed with exit code \(code): \(stderr)"
    case .timedOut(let timeout):
      return "tokencat snapshot timed out after \(Int(timeout)) seconds."
    }
  }
}

protocol TokenCatProcessRunning {
  func run(
    executableURL: URL,
    arguments: [String],
    environment: [String: String],
    currentDirectoryURL: URL,
    timeout: TimeInterval
  ) throws -> ProcessResult
}

struct ProcessResult: Equatable {
  let stdout: Data
  let stderr: String
  let terminationStatus: Int32
}

struct FoundationProcessRunner: TokenCatProcessRunning {
  func run(
    executableURL: URL,
    arguments: [String],
    environment: [String: String],
    currentDirectoryURL: URL,
    timeout: TimeInterval
  ) throws -> ProcessResult {
    let process = Process()
    process.executableURL = executableURL
    process.arguments = arguments
    process.environment = environment
    process.currentDirectoryURL = currentDirectoryURL

    let stdout = Pipe()
    let stderr = Pipe()
    process.standardOutput = stdout
    process.standardError = stderr

    try process.run()
    let deadline = Date().addingTimeInterval(timeout)
    while process.isRunning {
      if Date() > deadline {
        process.terminate()
        throw TokenCatBridgeError.timedOut(timeout)
      }
      Thread.sleep(forTimeInterval: 0.05)
    }

    return ProcessResult(
      stdout: stdout.fileHandleForReading.readDataToEndOfFile(),
      stderr: String(data: stderr.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? "",
      terminationStatus: process.terminationStatus
    )
  }
}

struct TokenCatBridge {
  let pythonURL: URL
  let repositoryRootURL: URL
  let runner: TokenCatProcessRunning
  let timeout: TimeInterval
  let configurationError: TokenCatBridgeError?

  init(
    pythonURL: URL,
    repositoryRootURL: URL,
    runner: TokenCatProcessRunning = FoundationProcessRunner(),
    timeout: TimeInterval = 30
  ) {
    self.pythonURL = pythonURL
    self.repositoryRootURL = repositoryRootURL
    self.runner = runner
    self.timeout = timeout
    self.configurationError = nil
  }

  private init(error: TokenCatBridgeError, runner: TokenCatProcessRunning = FoundationProcessRunner()) {
    self.pythonURL = URL(fileURLWithPath: "/")
    self.repositoryRootURL = URL(fileURLWithPath: "/")
    self.runner = runner
    self.timeout = 30
    self.configurationError = error
  }

  static func developmentDefault(environment: [String: String] = ProcessInfo.processInfo.environment) -> TokenCatBridge {
    guard let pythonPath = environment["TOKENCAT_PYTHON"], !pythonPath.isEmpty else {
      return TokenCatBridge(error: .missingEnvironment("TOKENCAT_PYTHON"))
    }
    guard let rootPath = environment["TOKENCAT_ROOT"], !rootPath.isEmpty else {
      return TokenCatBridge(error: .missingEnvironment("TOKENCAT_ROOT"))
    }
    return TokenCatBridge(
      pythonURL: URL(fileURLWithPath: pythonPath),
      repositoryRootURL: URL(fileURLWithPath: rootPath),
      runner: FoundationProcessRunner()
    )
  }

  func fetchSnapshot() throws -> TokenCatSnapshot {
    if let configurationError {
      throw configurationError
    }
    guard FileManager.default.fileExists(atPath: pythonURL.path) else {
      throw TokenCatBridgeError.invalidPythonPath(pythonURL.path)
    }

    var environment = ProcessInfo.processInfo.environment
    environment["PYTHONPATH"] = repositoryRootURL.appendingPathComponent("src").path

    let result = try runner.run(
      executableURL: pythonURL,
      arguments: ["-m", "tokencat", "snapshot", "--since", "7d"],
      environment: environment,
      currentDirectoryURL: repositoryRootURL,
      timeout: timeout
    )

    guard result.terminationStatus == 0 else {
      throw TokenCatBridgeError.processFailed(result.terminationStatus, result.stderr.trimmingCharacters(in: .whitespacesAndNewlines))
    }

    return try JSONDecoder.tokenCatSnapshotDecoder.decode(TokenCatSnapshot.self, from: result.stdout)
  }
}
