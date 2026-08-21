import { runCli, assertOk } from "../inner_skills/feishu-calendar/scripts/_cli.js";
import { parseTimeToTimestamp, formatTimestamp } from "../inner_skills/feishu-calendar/scripts/_time.js";

function pickCalendarId(primaryRes) {
  return (
    primaryRes?.data?.calendars?.[0]?.calendar?.calendar_id ??
    primaryRes?.calendars?.[0]?.calendar?.calendar_id ??
    null
  );
}

function fmtEventBase(e) {
  if (!e) return e;
  const startTs = e?.start_time?.timestamp;
  const endTs = e?.end_time?.timestamp;
  return {
    event_id: e.event_id,
    summary: e.summary,
    description: e.description,
    status: e.status,
    visibility: e.visibility,
    free_busy_status: e.free_busy_status,
    start: startTs ? formatTimestamp(startTs) : undefined,
    end: endTs ? formatTimestamp(endTs) : undefined,
    start_ts: startTs,
    end_ts: endTs,
  };
}

function isTentativeOrNeedsAction(rsvp) {
  return rsvp === "needs_action" || rsvp === "tentative";
}

function isDeclined(rsvp) {
  return rsvp === "decline" || rsvp === "removed";
}

function shouldBlockByStatus(eventStatus) {
  // Calendar event status: typically "confirmed" or "cancelled".
  // If cancelled, never blocks.
  if (!eventStatus) return true; // unknown: conservative
  return eventStatus !== "cancelled";
}

function mergeIntervals(intervals) {
  const xs = (intervals || [])
    .filter((it) => it && it.start && it.end && it.start < it.end)
    .sort((a, b) => a.start - b.start);
  const out = [];
  for (const cur of xs) {
    if (out.length === 0) {
      out.push({ ...cur });
      continue;
    }
    const last = out[out.length - 1];
    if (cur.start <= last.end) {
      last.end = Math.max(last.end, cur.end);
    } else {
      out.push({ ...cur });
    }
  }
  return out;
}

function invertIntervals(windowStart, windowEnd, busy) {
  const merged = mergeIntervals(busy);
  const free = [];
  let cursor = windowStart;
  for (const b of merged) {
    if (b.end <= cursor) continue;
    if (b.start > cursor) {
      free.push({ start: cursor, end: Math.min(b.start, windowEnd) });
    }
    cursor = Math.max(cursor, b.end);
    if (cursor >= windowEnd) break;
  }
  if (cursor < windowEnd) free.push({ start: cursor, end: windowEnd });
  return free.filter((x) => x.end > x.start);
}

function toHm(tsSec) {
  const d = new Date(tsSec * 1000);
  // show in Asia/Shanghai (UTC+8)
  const local = new Date(d.getTime() + 8 * 3600 * 1000);
  const hh = String(local.getUTCHours()).padStart(2, "0");
  const mm = String(local.getUTCMinutes()).padStart(2, "0");
  return `${hh}:${mm}`;
}

await runCli(async ({ sdk, opts, input }) => {
  const p = input ?? {};
  if (p.action !== "list_user_events") {
    throw new Error("unsupported action (expected: list_user_events)");
  }
  if (!p.user_open_id) throw new Error("missing user_open_id");
  if (!p.start_time) throw new Error("missing start_time");
  if (!p.end_time) throw new Error("missing end_time");

  const startTs = parseTimeToTimestamp(p.start_time);
  const endTs = parseTimeToTimestamp(p.end_time);
  if (!startTs || !endTs) throw new Error("invalid start_time/end_time");

  // token_mode:
  // - "tenant": try tenant token (opts={})
  // - "user": use current sender's user token (opts)
  const tokenMode = p.token_mode || "tenant";
  const callOpts = tokenMode === "user" ? opts : {};

  const primaryRes = await sdk.calendar.calendar.primary(
    {
      params: {
        user_id_type: "open_id",
        user_id: String(p.user_open_id),
      },
    },
    callOpts,
  );
  assertOk(primaryRes);
  const calendarId = pickCalendarId(primaryRes);
  if (!calendarId) throw new Error("could not resolve target user's primary calendar_id");

  const listRes = await sdk.calendar.calendarEvent.instanceView(
    {
      path: { calendar_id: calendarId },
      params: {
        start_time: startTs,
        end_time: endTs,
        user_id_type: "open_id",
      },
    },
    callOpts,
  );
  assertOk(listRes);

  const rawEvents = listRes.data?.items ?? [];

  const outEvents = [];
  const blockingIntervals = [];

  for (const e of rawEvents) {
    const base = fmtEventBase(e);

    // Try read attendee list and locate the target user rsvp
    let targetRsvp = undefined;
    let attendeeError = undefined;
    try {
      const attRes = await sdk.calendar.calendarEventAttendee.list(
        {
          path: { calendar_id: calendarId, event_id: e.event_id },
          params: { user_id_type: "open_id", page_size: 500 },
        },
        callOpts,
      );
      assertOk(attRes);
      const attendees = attRes.data?.items ?? [];
      const me = attendees.find((a) => a.user_id === p.user_open_id || a.id === p.user_open_id);
      targetRsvp = me?.rsvp_status;
    } catch (err) {
      attendeeError = err instanceof Error ? err.message : String(err);
    }

    // Decide if this event counts as a "real" conflict
    let isBlocking = shouldBlockByStatus(base.status);

    // If we can see RSVP: exclude needs_action / tentative / decline / removed
    if (targetRsvp) {
      if (isTentativeOrNeedsAction(targetRsvp) || isDeclined(targetRsvp)) {
        isBlocking = false;
      }
    }

    if (isBlocking && base.start_ts && base.end_ts) {
      blockingIntervals.push({ start: Number(base.start_ts), end: Number(base.end_ts), event_id: base.event_id });
    }

    outEvents.push({
      ...base,
      target_rsvp_status: targetRsvp,
      attendee_error: attendeeError,
      is_blocking: isBlocking,
    });
  }

  const windowStart = Number(startTs);
  const windowEnd = Number(endTs);
  const mergedBusy = mergeIntervals(blockingIntervals);
  const free = invertIntervals(windowStart, windowEnd, mergedBusy);

  const minSec = Number(p.min_slot_minutes ?? 40) * 60;
  const freeSlots = free
    .filter((x) => x.end - x.start >= minSec)
    .map((x) => ({
      start: formatTimestamp(String(x.start)),
      end: formatTimestamp(String(x.end)),
      start_hm: toHm(x.start),
      end_hm: toHm(x.end),
      duration_min: Math.floor((x.end - x.start) / 60),
    }));

  return {
    user_open_id: p.user_open_id,
    calendar_id: calendarId,
    query_window: {
      start_time: formatTimestamp(startTs),
      end_time: formatTimestamp(endTs),
    },
    events: outEvents,
    blocking_busy_merged: mergedBusy.map((x) => ({ start: formatTimestamp(String(x.start)), end: formatTimestamp(String(x.end)) })),
    free_slots_gte_40m: freeSlots,
  };
});
