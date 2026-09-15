import ActivityKit
import SwiftUI
import WidgetKit

private let honey = Color(red: 1, green: 0.83, blue: 0.16)

@main
struct RunActivityBundle: WidgetBundle {
  var body: some Widget { RunActivityWidget() }
}

struct RunActivityWidget: Widget {
  var body: some WidgetConfiguration {
    ActivityConfiguration(for: RunActivityAttributes.self) { context in
      VStack(alignment: .leading, spacing: 12) {
        HStack {
          Label(context.attributes.simulation ? "TerraRun · Virtual run" : "TerraRun", systemImage: "figure.run")
            .font(.system(.subheadline, design: .rounded).weight(.semibold)).foregroundStyle(honey)
          Spacer()
          Text(status(context)).font(.caption).foregroundStyle(.white.opacity(0.7))
        }
        HStack(alignment: .top) {
          metric("DISTANCE", distance(context), unit(context))
          Spacer()
          VStack(alignment: .leading, spacing: 4) {
            Text("ELAPSED").font(.caption2).foregroundStyle(.white.opacity(0.6))
            RunTimer(context: context).font(.system(.title2, design: .rounded).weight(.bold)).monospacedDigit()
          }
          Spacer()
          metric("PACE", pace(context), "/" + unit(context))
        }
      }
      .padding(18).foregroundStyle(.white)
      .activityBackgroundTint(Color(red: 0.07, green: 0.09, blue: 0.08))
      .activitySystemActionForegroundColor(honey)
      .widgetURL(URL(string: "run://"))
    } dynamicIsland: { context in
      DynamicIsland {
        DynamicIslandExpandedRegion(.leading) {
          Label(context.attributes.simulation ? "Virtual run" : "TerraRun", systemImage: "figure.run")
            .font(.caption.weight(.semibold)).foregroundStyle(honey)
        }
        DynamicIslandExpandedRegion(.trailing) {
          RunTimer(context: context).font(.subheadline.weight(.semibold)).monospacedDigit().frame(width: 82)
        }
        DynamicIslandExpandedRegion(.bottom) {
          HStack {
            metric("DISTANCE", distance(context), unit(context))
            Spacer()
            metric("PACE", pace(context), "/" + unit(context))
          }.padding(.top, 8)
        }
      } compactLeading: {
        Image(systemName: "figure.run").foregroundStyle(honey)
      } compactTrailing: {
        Text(distance(context)).font(.caption.weight(.bold)).monospacedDigit().foregroundStyle(honey)
          .accessibilityLabel(distance(context) + " " + unit(context))
      } minimal: {
        Image(systemName: "figure.run").foregroundStyle(honey)
      }
      .keylineTint(honey)
      .widgetURL(URL(string: "run://"))
    }
  }
  private func unit(_ c: ActivityViewContext<RunActivityAttributes>) -> String { c.state.units == "mi" ? "mi" : "km" }
  private func distance(_ c: ActivityViewContext<RunActivityAttributes>) -> String {
    String(format: "%.2f", c.state.distanceM / (c.state.units == "mi" ? 1609.344 : 1000))
  }
  private func pace(_ c: ActivityViewContext<RunActivityAttributes>) -> String {
    guard !c.isStale, let seconds = c.state.paceSeconds, seconds.isFinite, seconds > 0 else { return "—" }
    let value = Int(seconds.rounded())
    return String(format: "%d:%02d", value / 60, value % 60)
  }
  private func status(_ c: ActivityViewContext<RunActivityAttributes>) -> String {
    if c.state.interrupted { return "Run interrupted" }
    if c.state.endedAt != nil { return "Run finished" }
    return c.isStale ? "Waiting for GPS" : "Recording"
  }
  private func metric(_ label: String, _ value: String, _ unit: String) -> some View {
    VStack(alignment: .leading, spacing: 4) {
      Text(label).font(.caption2).foregroundStyle(.white.opacity(0.6))
      HStack(alignment: .firstTextBaseline, spacing: 3) {
        Text(value).font(.system(.title2, design: .rounded).weight(.bold)).monospacedDigit()
        Text(unit).font(.caption).foregroundStyle(.white.opacity(0.7))
      }
    }
  }
}

private struct RunTimer: View {
  let context: ActivityViewContext<RunActivityAttributes>
  var body: some View {
    if let ended = context.state.endedAt {
      let seconds = max(0, Int(ended.timeIntervalSince(context.attributes.startedAt)))
      Text(String(format: "%d:%02d:%02d", seconds / 3600, seconds / 60 % 60, seconds % 60))
    } else {
      // The system ticks this text while JS sleeps. GPS drives only distance/pace.
      Text(timerInterval: context.attributes.startedAt...context.attributes.startedAt.addingTimeInterval(8 * 3600), countsDown: false)
    }
  }
}
