import { createContext, useContext, useState, type ReactNode } from "react";
import { datePresets, presetRange, type DatePreset, type DateRange } from "../utils/dateRange";
import "../styles/date-presets.css";

const DateRangeContext = createContext<{
  range: DateRange;
  setRange: (range: DateRange) => void;
} | null>(null);

export function DateRangeProvider({ children }: { children: ReactNode }) {
  const [range, setRange] = useState(() => presetRange("this-month"));
  return <DateRangeContext.Provider value={{ range, setRange }}>{children}</DateRangeContext.Provider>;
}

export function useReportPeriod() {
  const context = useContext(DateRangeContext);
  if (!context) throw new Error("Report period provider is missing.");
  return context;
}

export function DateRangeControls({ range, onChange, onPreset, disabled = false, label = "Report period" }: {
  range: DateRange;
  onChange: (range: DateRange) => void;
  onPreset?: (range: DateRange) => void;
  disabled?: boolean;
  label?: string;
}) {
  const candidates = [...datePresets].sort((left, right) => Number(right.key === range.preset) - Number(left.key === range.preset));
  const active = candidates.find(preset => {
    const candidate = presetRange(preset.key);
    return candidate.from === range.from && candidate.to === range.to;
  })?.key ?? "custom";

  return <div className="date-range-controls" role="group" aria-label={label}>
    <select aria-label={`${label} preset`} value={active} disabled={disabled} onChange={event => {
      if (event.target.value === "custom") return;
      const next = presetRange(event.target.value as DatePreset);
      onChange(next);
      onPreset?.(next);
    }}>
      <option value="custom">Custom dates</option>
      {datePresets.map(preset => <option key={preset.key} value={preset.key}>{preset.label}</option>)}
    </select>
    <input aria-label={`${label} from`} type="date" value={range.from} max={range.to || undefined}
      disabled={disabled} onChange={event => onChange({ ...range, from: event.target.value, preset: undefined })} />
    <input aria-label={`${label} to`} type="date" value={range.to} min={range.from || undefined}
      disabled={disabled} onChange={event => onChange({ ...range, to: event.target.value, preset: undefined })} />
  </div>;
}
