import ActivityKit
import ExpoModulesCore
import UIKit

public class RunLiveActivityModule: Module {
  public func definition() -> ModuleDefinition {
    Name("RunLiveActivity")

    AsyncFunction("isAvailable") { () -> Bool in
      if #available(iOS 16.2, *) { return ActivityAuthorizationInfo().areActivitiesEnabled }
      return false
    }

    AsyncFunction("start") { (runId: String, startedAtMs: Double, simulation: Bool, units: String) async throws -> Bool in
      guard #available(iOS 16.2, *) else { return false }
      guard ActivityAuthorizationInfo().areActivitiesEnabled else { return false }
      // ActivityKit only permits a local start while the app is foregrounded.
      guard await MainActor.run(body: { UIApplication.shared.applicationState == .active }) else { return false }
      for activity in Activity<RunActivityAttributes>.activities {
        await activity.end(nil, dismissalPolicy: .immediate)
      }
      let state = RunActivityAttributes.ContentState(distanceM: 0, paceSeconds: nil, units: units, updatedAt: Date(), endedAt: nil, interrupted: false)
      _ = try Activity.request(
        attributes: RunActivityAttributes(runId: runId, startedAt: Date(timeIntervalSince1970: startedAtMs / 1000), simulation: simulation),
        content: ActivityContent(state: state, staleDate: Date().addingTimeInterval(25)), pushType: nil
      )
      return true
    }

    AsyncFunction("update") { (runId: String, distanceM: Double, paceSeconds: Double?, units: String) async -> Void in
      guard #available(iOS 16.2, *) else { return }
      for activity in Activity<RunActivityAttributes>.activities where activity.attributes.runId == runId {
        let state = RunActivityAttributes.ContentState(distanceM: max(0, distanceM), paceSeconds: paceSeconds, units: units, updatedAt: Date(), endedAt: nil, interrupted: false)
        await activity.update(ActivityContent(state: state, staleDate: Date().addingTimeInterval(25)))
      }
    }

    AsyncFunction("end") { (runId: String, distanceM: Double, endedAtMs: Double) async -> Void in
      guard #available(iOS 16.2, *) else { return }
      for activity in Activity<RunActivityAttributes>.activities where activity.attributes.runId == runId {
        var state = activity.content.state
        state.distanceM = max(0, distanceM)
        state.endedAt = Date(timeIntervalSince1970: endedAtMs / 1000)
        await activity.end(ActivityContent(state: state, staleDate: nil), dismissalPolicy: .after(Date().addingTimeInterval(60)))
      }
    }

    AsyncFunction("endAll") { () async -> Void in
      guard #available(iOS 16.2, *) else { return }
      for activity in Activity<RunActivityAttributes>.activities {
        var state = activity.content.state
        state.endedAt = state.updatedAt
        state.interrupted = true
        await activity.end(ActivityContent(state: state, staleDate: nil), dismissalPolicy: .immediate)
      }
    }
  }
}
