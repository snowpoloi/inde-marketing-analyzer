const labels: Record<string, string> = {
  success: "Success",
  failed: "Failed",
  running: "Running",
  skipped: "Skipped",
  scale: "Scale",
  reduce: "Reduce",
  pause: "Pause",
  "investigate tracking": "Tracking",
  "investigate product/feed": "Feed",
  monitor: "Monitor",
  positive: "Positive",
  medium: "Medium",
  high: "High"
};

export function StatusBadge({ value }: { value: string }) {
  const normalized = value.toLowerCase();
  return <span className={`badge badge-${normalized.replace(/[^a-z]+/g, "-")}`}>{labels[normalized] ?? value}</span>;
}

