import { runCli, assertOk } from "../inner_skills/feishu-calendar/scripts/_cli.js";
import { parseTimeToTimestamp, formatTimestamp } from "../inner_skills/feishu-calendar/scripts/_time.js";

function pickCalendarId(primaryRes) {
  return (
    primaryRes?.data?.calendars?.[0]?.calendar?.calendar_id ??
    primaryRes?.calendars?.[0]?.calendar?.calendar_id ??
    null
  );
}

await runCli(async ({ sdk, opts, input }) => {
  const p = input ?? {};
  if (p.action !== "find_attendee_rsvp_in_my_events") {
    throw new Error("unsupported action (expected: find_attendee_rsvp_in_my_events)");
  }
  if (!p.target_user_open_id) throw new Error("missing target_user_open_id");
  if (!p.start_time) throw new Error("missing start_time");
  if (!p.end_time) throw new Error("missing end_time");

  const startTs = parseTimeToTimestamp(p.start_time);
  const endTs = parseTimeToTimestamp(p.end_time);
  if (!startTs || !endTs) throw new Error("invalid start_time/end_time");

  const calRes = await sdk.calendar.calendar.primary({}, opts);
  assertOk(calRes);
  const calendarId = pickCalendarId(calRes);
  if (!calendarId) throw new Error("could not resolve my primary calendar_id");

  const listRes = await sdk.calendar.calendarEvent.instanceView(
    {
      path: { calendar_id: calendarId },
      params: { start_time: startTs, end_time: endTs, user_id_type: "open_id" },
    },
    opts,
  );
  assertOk(listRes);

  const events = listRes.data?.items ?? [];
  const hits = [];

  for (const e of events) {
    let rsvp = null;
    let isOrganizer = false;
    let attendeeError = null;
    try {
      const attRes = await sdk.calendar.calendarEventAttendee.list(
        {
          path: { calendar_id: calendarId, event_id: e.event_id },
          params: { user_id_type: "open_id", page_size: 500 },
        },
        opts,
      );
      assertOk(attRes);
      const attendees = attRes.data?.items ?? [];
      const t = attendees.find((a) => a.user_id === p.target_user_open_id || a.id === p.target_user_open_id);
      if (t) {
        rsvp = t.rsvp_status ?? null;
        isOrganizer = !!t.is_organizer;
      }
    } catch (err) {
      attendeeError = err instanceof Error ? err.message : String(err);
    }

    if (rsvp !== null) {
      hits.push({
        event_id: e.event_id,
        summary: e.summary,
        start: formatTimestamp(e.start_time?.timestamp),
        end: formatTimestamp(e.end_time?.timestamp),
        event_status: e.status,
        target_rsvp_status: rsvp,
        target_is_organizer: isOrganizer,
        attendee_error: attendeeError,
      });
    }
  }

  return {
    target_user_open_id: p.target_user_open_id,
    query_window: { start: formatTimestamp(startTs), end: formatTimestamp(endTs) },
    matched_events_count: hits.length,
    matched_events: hits,
  };
});
