export type DateRange = { from: string; to: string; preset?: DatePreset };
export type DatePreset = "today" | "yesterday" | "last-7" | "this-month" | "previous-month";

export const datePresets: { key: DatePreset; label: string }[] = [
  { key: "today", label: "Today" },
  { key: "yesterday", label: "Yesterday" },
  { key: "last-7", label: "Last 7 days" },
  { key: "this-month", label: "This month" },
  { key: "previous-month", label: "Previous month" }
];

export function localIso(value: Date) {
  return `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, "0")}-${String(value.getDate()).padStart(2, "0")}`;
}

export function presetRange(preset: DatePreset, now = new Date()): DateRange {
  const start = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const end = new Date(start);
  if (preset === "yesterday") {
    start.setDate(start.getDate() - 1);
    end.setDate(end.getDate() - 1);
  } else if (preset === "last-7") {
    start.setDate(start.getDate() - 6);
  } else if (preset === "this-month") {
    start.setDate(1);
  } else if (preset === "previous-month") {
    start.setDate(1);
    start.setMonth(start.getMonth() - 1);
    end.setDate(0);
  }
  return { from: localIso(start), to: localIso(end), preset };
}
