import Foundation

// Cargo test emits a hashed static archive. Install that exact tested artifact
// at the C link path also used by normal source builds.
let arguments = CommandLine.arguments
guard arguments.count == 3 else { fatalError("Expected Cargo artifact log and destination") }
let log = try String(contentsOfFile: arguments[1], encoding: .utf8)
var artifacts = Set<String>()
for line in log.split(separator: "\n") {
    guard line.first == "{" else { print(line); continue }
    let value = try JSONSerialization.jsonObject(with: Data(line.utf8)) as? [String: Any]
    guard value?["reason"] as? String == "compiler-artifact",
          let target = value?["target"] as? [String: Any],
          target["name"] as? String == "tokencat_core",
          let filenames = value?["filenames"] as? [String] else { continue }
    artifacts.formUnion(filenames.filter { $0.hasSuffix(".a") })
}
guard artifacts.count == 1, let artifact = artifacts.first else {
    fatalError("Cargo did not report exactly one tested tokencat_core static archive")
}
let destination = URL(fileURLWithPath: arguments[2])
let data = try Data(contentsOf: URL(fileURLWithPath: artifact))
try data.write(to: destination, options: .atomic)
