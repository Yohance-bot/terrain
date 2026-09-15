import ActivityKit
import Foundation

@available(iOS 16.2, *)
struct RunActivityAttributes: ActivityAttributes {
  struct ContentState: Codable, Hashable {
    var distanceM: Double
    var paceSeconds: Double?
    var units: String
    var updatedAt: Date
    var endedAt: Date?
    var interrupted: Bool
  }
  var runId: String
  var startedAt: Date
  var simulation: Bool
}
