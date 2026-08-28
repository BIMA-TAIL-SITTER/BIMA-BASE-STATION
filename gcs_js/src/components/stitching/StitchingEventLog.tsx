import type {
  StitchEventRecord,
} from "@/types/stitching";
import type { StitchWebSocketState } from "@/hooks/useStitchWebSocket";

interface StitchingEventLogProps {
  events: StitchEventRecord[];
  connectionState: StitchWebSocketState;
}

function describeEvent(event: StitchEventRecord): {
  label: string;
  detail: string;
  tone: string;
} {
  if (event.type === "file_detected") {
    return {
      label: "File detected",
      detail: `${event.file} (${event.total_images} total)`,
      tone: "is-info",
    };
  }
  if (event.type === "stitching_started") {
    return {
      label: "Stitching started",
      detail: `${event.image_count} source images`,
      tone: "is-warning",
    };
  }
  return event.success
    ? {
        label: "Stitching completed",
        detail: `Finished in ${event.elapsed_time.toFixed(2)} seconds`,
        tone: "is-success",
      }
    : {
        label: "Stitching failed",
        detail: event.error_message || "The engine did not produce an output.",
        tone: "is-danger",
      };
}

export function StitchingEventLog({
  events,
  connectionState,
}: StitchingEventLogProps) {
  return (
    <section className="operations-section stitching-event-section">
      <div className="operations-section-heading">
        <div>
          <h2>Live Event Log</h2>
          <span>Image detection and engine state changes.</span>
        </div>
        <strong className={`stitching-connection-state is-${connectionState}`}>
          {connectionState === "live" ? "LIVE" : connectionState.toUpperCase()}
        </strong>
      </div>

      {events.length ? (
        <ol className="stitching-event-list" aria-live="polite">
          {[...events].reverse().map((event) => {
            const description = describeEvent(event);
            return (
              <li key={event.id} className={description.tone}>
                <time>{event.receivedAt}</time>
                <div>
                  <strong>{description.label}</strong>
                  <span>{description.detail}</span>
                </div>
              </li>
            );
          })}
        </ol>
      ) : (
        <div className="operations-empty-state">
          <strong>No events received</strong>
          <span>Events from the selected session will appear in real time.</span>
        </div>
      )}
    </section>
  );
}
