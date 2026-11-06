// Period presets of the change-history page, always in Athens time (the owner's day), whatever the browser's zone.

export type ChangePeriod = "today" | "yesterday" | "last-7" | "last-30" | "this-week" | "this-month" | "previous-month";

export const changePeriods: { key: ChangePeriod; label: string }[] = [
  { key: "today", label: "Σήμερα" },
  { key: "yesterday", label: "Χθες" },
  { key: "last-7", label: "7 ημέρες" },
  { key: "last-30", label: "30 ημέρες" },
  { key: "this-week", label: "Αυτή η εβδομάδα" },
  { key: "this-month", label: "Αυτός ο μήνας" },
  { key: "previous-month", label: "Προηγούμενος μήνας" }
];

// The server accepts windows of up to 93 days.
export const MAX_CHANGE_DAYS = 93;

const athensParts = new Intl.DateTimeFormat("en-GB", {
  timeZone: "Europe/Athens", year: "numeric", month: "2-digit", day: "2-digit"
});

function pad(value: number) {
  return String(value).padStart(2, "0");
}

function parseDay(iso: string) {
  const [year, month, day] = iso.split("-").map(Number);
  return new Date(Date.UTC(year, month - 1, day));
}

function formatDay(value: Date) {
  return `${value.getUTCFullYear()}-${pad(value.getUTCMonth() + 1)}-${pad(value.getUTCDate())}`;
}

export function addDays(iso: string, days: number) {
  const value = parseDay(iso);
  value.setUTCDate(value.getUTCDate() + days);
  return formatDay(value);
}

// Today's date in Athens as YYYY-MM-DD.
export function athensToday(now = new Date()) {
  const parts = athensParts.formatToParts(now);
  const part = (type: string) => parts.find((item) => item.type === type)?.value ?? "";
  return `${part("year")}-${part("month")}-${part("day")}`;
}

export function changePeriodRange(period: ChangePeriod, now = new Date()): { from: string; to: string } {
  const today = athensToday(now);
  if (period === "yesterday") {
    const yesterday = addDays(today, -1);
    return { from: yesterday, to: yesterday };
  }
  if (period === "last-7") return { from: addDays(today, -6), to: today };
  if (period === "last-30") return { from: addDays(today, -29), to: today };
  if (period === "this-week") {
    const sinceMonday = (parseDay(today).getUTCDay() + 6) % 7;
    return { from: addDays(today, -sinceMonday), to: today };
  }
  if (period === "this-month") return { from: `${today.slice(0, 8)}01`, to: today };
  if (period === "previous-month") {
    const lastDay = addDays(`${today.slice(0, 8)}01`, -1);
    return { from: `${lastDay.slice(0, 8)}01`, to: lastDay };
  }
  return { from: today, to: today };
}

// Days in a window, both ends included.
export function windowDays(from: string, to: string) {
  return Math.round((parseDay(to).getTime() - parseDay(from).getTime()) / 86_400_000) + 1;
}
