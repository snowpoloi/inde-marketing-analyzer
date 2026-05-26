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
  "investigate operations": "Operations",
  "review landing page": "Landing page",
  monitor: "Monitor",
  info: "Info",
  low: "Low",
  positive: "Positive",
  medium: "Medium",
  high: "High",
  critical: "Critical"
};

export function StatusBadge({ value }: { value: string }) {
  const normalized = value.toLowerCase();
  return <span className={`badge badge-${normalized.replace(/[^a-z]+/g, "-")}`}>{labels[normalized] ?? value}</span>;
}
