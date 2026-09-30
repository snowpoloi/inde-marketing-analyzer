import { useEffect, useMemo, useState } from "react";
import {
  CalendarRange,
  CheckCircle2,
  Clock3,
  ListFilter,
  Plus,
  RefreshCw,
  ShoppingCart,
  Trash2,
  XCircle
} from "lucide-react";
import { api } from "../api/client";
import type {
  OrderAnalytics,
  OrderAnalyticsOptions,
  OrderAnalyticsPeriod,
  OrderAnalyticsPeriodInput,
  OrderAnalyticsRequest,
  OrderStatusAging,
  StaleOrder
} from "../api/client";
import { DataTable } from "../components/DataTable";
import type { Column } from "../components/DataTable";
import { StatCard } from "../components/StatCard";
import { StatusBadge } from "../components/StatusBadge";
import "../styles/date-presets.css";

const number = new Intl.NumberFormat("el-GR", { maximumFractionDigits: 1 });
const currency = new Intl.NumberFormat("el-GR", { style: "currency", currency: "EUR" });
const dateFormatter = new Intl.DateTimeFormat("el-GR", { day: "2-digit", month: "2-digit", year: "numeric" });
const periodColors = ["#166b57", "#2f6fba", "#bd6b22", "#a23a55"];

const emptyOptions: OrderAnalyticsOptions = {
  statuses: [],
  aging_statuses: [],
  completed_statuses: [],
  cancelled_statuses: []
};

function localIso(value: Date) {
  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, "0");
  const day = String(value.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function shiftDays(value: Date, days: number) {
  const next = new Date(value);
  next.setDate(next.getDate() + days);
  return next;
}

function defaultPeriods(): OrderAnalyticsPeriodInput[] {
  const today = new Date();
  return [
    {
      key: "current",
      label: "Current period",
      date_from: localIso(shiftDays(today, -29)),
      date_to: localIso(today)
    },
    {
      key: "previous",
      label: "Previous period",
      date_from: localIso(shiftDays(today, -59)),
      date_to: localIso(shiftDays(today, -30))
    }
  ];
}

function formatDate(value: string) {
  const date = new Date(`${value.slice(0, 10)}T00:00:00`);
  return Number.isNaN(date.getTime()) ? value : dateFormatter.format(date);
}

function periodLength(period: OrderAnalyticsPeriodInput) {
  const start = new Date(`${period.date_from}T00:00:00`);
  const end = new Date(`${period.date_to}T00:00:00`);
  return Math.max(Math.round((end.getTime() - start.getTime()) / 86400000) + 1, 1);
}

function StatusPicker({
  title,
  options,
  selected,
  onChange
}: {
  title: string;
  options: OrderAnalyticsOptions["statuses"];
  selected: string[];
  onChange: (next: string[]) => void;
}) {
  const selectedSet = new Set(selected);
  function toggle(name: string, checked: boolean) {
    onChange(checked ? [...selected, name] : selected.filter((item) => item !== name));
  }

  return (
    <div className="analytics-status-picker">
      <div className="analytics-status-picker-head">
        <strong>{title}</strong>
        <span>{number.format(selected.length)}</span>
      </div>
      <div className="analytics-status-actions">
        <button type="button" onClick={() => onChange(options.map((option) => option.name))}>All</button>
        <button type="button" onClick={() => onChange([])}>None</button>
      </div>
      <div className="analytics-status-options">
        {options.map((option) => (
          <label key={option.name}>
            <input
              type="checkbox"
              checked={selectedSet.has(option.name)}
              onChange={(event) => toggle(option.name, event.target.checked)}
            />
            <span>{option.name}</span>
            <small>{number.format(option.orders)}</small>
          </label>
        ))}
      </div>
    </div>
  );
}

function ComparisonChart({
  title,
  metric,
  periods
}: {
  title: string;
  metric: "orders" | "completed";
  periods: OrderAnalyticsPeriod[];
}) {
  const width = 960;
  const height = 280;
  const pad = { top: 18, right: 22, bottom: 38, left: 52 };
  const plotWidth = width - pad.left - pad.right;
  const plotHeight = height - pad.top - pad.bottom;
  const pointCount = Math.max(...periods.map((period) => period.series.length), 1);
  const maxValue = Math.max(...periods.flatMap((period) => period.series.map((point) => point[metric])), 1);
  const yMax = Math.max(Math.ceil(maxValue / 5) * 5, 5);
  const x = (index: number) => pad.left + (pointCount <= 1 ? plotWidth / 2 : (index / (pointCount - 1)) * plotWidth);
  const y = (value: number) => pad.top + plotHeight - (value / yMax) * plotHeight;
  const xTicks = Array.from(new Set([0, Math.floor((pointCount - 1) / 2), pointCount - 1]));
  const yTicks = [0, 0.25, 0.5, 0.75, 1];

  return (
    <section className="panel analytics-chart-panel">
      <div className="panel-title tight">
        <h2>{title}</h2>
      </div>
      <div className="analytics-chart-legend">
        {periods.map((period, index) => (
          <span key={period.key}>
            <i style={{ background: periodColors[index] }} />
            {period.label}
          </span>
        ))}
      </div>
      <div className="analytics-chart-canvas">
        <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={title}>
          {yTicks.map((tick) => {
            const value = Math.round(yMax * tick);
            const yPosition = y(value);
            return (
              <g key={tick}>
                <line x1={pad.left} y1={yPosition} x2={width - pad.right} y2={yPosition} className="chart-grid-line" />
                <text x={pad.left - 10} y={yPosition + 4} textAnchor="end" className="chart-axis-label">{value}</text>
              </g>
            );
          })}
          {xTicks.map((tick) => (
            <text key={tick} x={x(tick)} y={height - 12} textAnchor="middle" className="chart-axis-label">
              {tick + 1}
            </text>
          ))}
          {periods.map((period, periodIndex) => {
            const points = period.series.map((point, index) => `${x(index)},${y(point[metric])}`).join(" ");
            return (
              <g key={period.key}>
                <polyline
                  points={points}
                  fill="none"
                  stroke={periodColors[periodIndex]}
                  strokeWidth="3"
                  strokeLinejoin="round"
                  strokeLinecap="round"
                />
                {period.series.length <= 62
                  ? period.series.map((point, index) => (
                      <circle key={point.bucket} cx={x(index)} cy={y(point[metric])} r="3.5" fill={periodColors[periodIndex]}>
                        <title>{`${period.label} | ${point.bucket}: ${point[metric]}`}</title>
                      </circle>
                    ))
                  : null}
              </g>
            );
          })}
        </svg>
      </div>
    </section>
  );
}

export function OrderAnalyticsPage() {
  const [periods, setPeriods] = useState<OrderAnalyticsPeriodInput[]>(defaultPeriods);
  const [groupBy, setGroupBy] = useState<"day" | "month">("day");
  const [staleDays, setStaleDays] = useState(3);
  const [options, setOptions] = useState<OrderAnalyticsOptions>(emptyOptions);
  const [displayedStatuses, setDisplayedStatuses] = useState<string[]>([]);
  const [agingStatuses, setAgingStatuses] = useState<string[]>([]);
  const [completedStatuses, setCompletedStatuses] = useState<string[]>([]);
  const [cancelledStatuses, setCancelledStatuses] = useState<string[]>([]);
  const [analytics, setAnalytics] = useState<OrderAnalytics | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function fetchAnalytics(payload: OrderAnalyticsRequest) {
    setLoading(true);
    setError("");
    try {
      const result = await api.orderAnalytics(payload);
      setAnalytics(result.data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load order analytics");
    } finally {
      setLoading(false);
    }
  }

  async function load() {
    await fetchAnalytics({
      periods,
      statuses: displayedStatuses,
      aging_statuses: agingStatuses,
      completed_statuses: completedStatuses,
      cancelled_statuses: cancelledStatuses,
      group_by: groupBy,
      stale_days: staleDays
    });
  }

  useEffect(() => {
    let active = true;
    async function initialize() {
      setLoading(true);
      setError("");
      try {
        const result = await api.orderAnalyticsOptions();
        if (!active) return;
        const nextOptions = result.data ?? emptyOptions;
        const allStatuses = nextOptions.statuses.map((status) => status.name);
        setOptions(nextOptions);
        setDisplayedStatuses(allStatuses);
        setAgingStatuses(nextOptions.aging_statuses);
        setCompletedStatuses(nextOptions.completed_statuses);
        setCancelledStatuses(nextOptions.cancelled_statuses);
        const analyticsResult = await api.orderAnalytics({
          periods,
          statuses: allStatuses,
          aging_statuses: nextOptions.aging_statuses,
          completed_statuses: nextOptions.completed_statuses,
          cancelled_statuses: nextOptions.cancelled_statuses,
          group_by: groupBy,
          stale_days: staleDays
        });
        if (active) setAnalytics(analyticsResult.data);
      } catch (err) {
        if (active) setError(err instanceof Error ? err.message : "Could not load order analytics");
      } finally {
        if (active) setLoading(false);
      }
    }
    initialize().catch(() => undefined);
    return () => {
      active = false;
    };
  }, []);

  function updatePeriod(key: string, patch: Partial<OrderAnalyticsPeriodInput>) {
    setPeriods((current) => current.map((period) => (period.key === key ? { ...period, ...patch } : period)));
  }

  function addPeriod() {
    setPeriods((current) => {
      if (current.length >= 4) return current;
      const previous = current[current.length - 1];
      const days = periodLength(previous);
      const nextEnd = shiftDays(new Date(`${previous.date_from}T00:00:00`), -1);
      const nextStart = shiftDays(nextEnd, -(days - 1));
      return [
        ...current,
        {
          key: `period-${Date.now()}`,
          label: `Period ${current.length + 1}`,
          date_from: localIso(nextStart),
          date_to: localIso(nextEnd)
        }
      ];
    });
  }

  const statusComparison = useMemo(() => {
    if (!analytics) return [];
    return options.statuses
      .filter((option) => displayedStatuses.includes(option.name))
      .map((option) => ({
        status: option.name,
        values: analytics.periods.map(
          (period) => period.status_counts.find((row) => row.status === option.name)?.orders ?? 0
        )
      }))
      .filter((row) => row.values.some((value) => value > 0));
  }, [analytics, displayedStatuses, options.statuses]);

  const appliedStaleDays = analytics?.stale_days ?? staleDays;
  const appliedGroupBy = analytics?.group_by ?? groupBy;

  const agingColumns: Column<OrderStatusAging>[] = useMemo(
    () => [
      { key: "status", header: "Status", render: (row) => <strong>{row.status}</strong> },
      { key: "orders", header: "Orders now", align: "right", render: (row) => number.format(row.orders) },
      { key: "stale", header: `At least ${appliedStaleDays} days`, align: "right", render: (row) => number.format(row.stale_orders) },
      { key: "average", header: "Average days", align: "right", render: (row) => number.format(row.average_days) },
      { key: "maximum", header: "Oldest", align: "right", render: (row) => `${number.format(row.max_days)} days` }
    ],
    [appliedStaleDays]
  );

  const staleColumns: Column<StaleOrder>[] = useMemo(
    () => [
      { key: "order", header: "Order", render: (row) => <strong>{row.order_id}</strong> },
      { key: "created", header: "Created", render: (row) => formatDate(row.date_added) },
      { key: "status", header: "Current status", render: (row) => row.status },
      { key: "since", header: "In status since", render: (row) => formatDate(row.status_since) },
      { key: "days", header: "Days", align: "right", render: (row) => <strong>{number.format(row.days_in_status)}</strong> },
      {
        key: "source",
        header: "Date quality",
        render: (row) => <StatusBadge value={row.age_source === "tracked" ? "Tracked" : "Estimated"} />
      },
      { key: "total", header: "Total", align: "right", render: (row) => currency.format(row.total) },
      {
        key: "methods",
        header: "Methods",
        render: (row) => (
          <div className="audit-title-cell">
            <strong>{row.payment_method || "-"}</strong>
            <span>{row.shipping_method || "-"}</span>
          </div>
        )
      }
    ],
    []
  );

  const primary = analytics?.summary;

  return (
    <div className="page-stack">
      <header className="page-header">
        <div>
          <h1>Order analytics</h1>
          <p>Order flow, final outcomes and time spent in the current OpenCart status.</p>
        </div>
        <button className="primary-action compact" onClick={() => load()} disabled={loading}>
          <RefreshCw size={17} />
          Refresh
        </button>
      </header>

      {error ? <div className="notice error">{error}</div> : null}

      <section className="panel analytics-filters">
        <div className="panel-title">
          <div>
            <h2>Comparison</h2>
            <span>Choose two to four periods and classify the statuses used as completed or cancelled.</span>
          </div>
          <div className="preset-tabs" aria-label="Chart interval">
            <button className={`date-preset ${groupBy === "day" ? "active" : ""}`} onClick={() => setGroupBy("day")}>Day</button>
            <button className={`date-preset ${groupBy === "month" ? "active" : ""}`} onClick={() => setGroupBy("month")}>Month</button>
          </div>
        </div>

        <div className="analytics-period-list">
          {periods.map((period, index) => (
            <div className="analytics-period-row" key={period.key}>
              <i style={{ background: periodColors[index] }} />
              <input
                aria-label={`Period ${index + 1} label`}
                value={period.label}
                onChange={(event) => updatePeriod(period.key, { label: event.target.value })}
              />
              <input
                aria-label={`${period.label} start`}
                type="date"
                value={period.date_from}
                onChange={(event) => updatePeriod(period.key, { date_from: event.target.value })}
              />
              <input
                aria-label={`${period.label} end`}
                type="date"
                value={period.date_to}
                onChange={(event) => updatePeriod(period.key, { date_to: event.target.value })}
              />
              <button
                className="icon-button danger"
                type="button"
                title="Remove period"
                aria-label={`Remove ${period.label}`}
                disabled={periods.length <= 2}
                onClick={() => setPeriods((current) => current.filter((item) => item.key !== period.key))}
              >
                <Trash2 size={17} />
              </button>
            </div>
          ))}
          <div className="analytics-filter-footer">
            <button className="secondary-action compact" type="button" onClick={addPeriod} disabled={periods.length >= 4}>
              <Plus size={17} />
              Add period
            </button>
            <label>
              <span>Stale after</span>
              <input
                type="number"
                min="0"
                max="3650"
                value={staleDays}
                onChange={(event) => setStaleDays(Math.min(Math.max(Number(event.target.value) || 0, 0), 3650))}
              />
              <span>days</span>
            </label>
          </div>
        </div>

        <div className="analytics-status-grid">
          <StatusPicker title="Displayed statuses" options={options.statuses} selected={displayedStatuses} onChange={setDisplayedStatuses} />
          <StatusPicker title="Aging statuses" options={options.statuses} selected={agingStatuses} onChange={setAgingStatuses} />
          <StatusPicker
            title="Completed statuses"
            options={options.statuses}
            selected={completedStatuses}
            onChange={(next) => {
              setCompletedStatuses(next);
              setCancelledStatuses((current) => current.filter((status) => !next.includes(status)));
            }}
          />
          <StatusPicker
            title="Cancelled statuses"
            options={options.statuses}
            selected={cancelledStatuses}
            onChange={(next) => {
              setCancelledStatuses(next);
              setCompletedStatuses((current) => current.filter((status) => !next.includes(status)));
            }}
          />
        </div>
      </section>

      <section className="stats-grid analytics-stats-grid">
        <StatCard label="Orders received" value={number.format(primary?.orders ?? 0)} detail={primary?.primary_period ?? "Current period"} icon={ShoppingCart} />
        <StatCard label="Completed" value={number.format(primary?.completed ?? 0)} detail={`${number.format(primary?.completion_rate ?? 0)}% completion`} icon={CheckCircle2} />
        <StatCard label="Cancelled" value={number.format(primary?.cancelled ?? 0)} detail="Selected cancelled statuses" icon={XCircle} />
        <StatCard label="Still open" value={number.format(primary?.open ?? 0)} detail="Neither completed nor cancelled" icon={ListFilter} />
        <StatCard label="Stale now" value={number.format(primary?.stale_orders ?? 0)} detail={`At least ${number.format(appliedStaleDays)} days in status`} icon={Clock3} />
      </section>

      {analytics ? (
        <>
          <div className="analytics-chart-grid">
            <ComparisonChart title="Orders received" metric="orders" periods={analytics.periods} />
            <ComparisonChart title="Orders completed" metric="completed" periods={analytics.periods} />
          </div>

          <section className="panel">
            <div className="panel-title">
              <h2>Period totals</h2>
              <span>{appliedGroupBy === "day" ? "Daily" : "Monthly"} comparison</span>
            </div>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Period</th>
                    <th>Date range</th>
                    <th className="align-right">Received</th>
                    <th className="align-right">Customers</th>
                    <th className="align-right">Completed</th>
                    <th className="align-right">Cancelled</th>
                    <th className="align-right">Open</th>
                    <th className="align-right">Subtotal</th>
                    <th className="align-right">Shipping</th>
                    <th className="align-right">Coupon</th>
                    <th className="align-right">Taxes</th>
                    <th className="align-right">Total value</th>
                    <th className="align-right">Avg. order value</th>
                    <th className="align-right">Completion</th>
                  </tr>
                </thead>
                <tbody>
                  {analytics.periods.map((period) => (
                    <tr key={period.key}>
                      <td><strong>{period.label}</strong></td>
                      <td>{formatDate(period.date_from)} - {formatDate(period.date_to)}</td>
                      <td className="align-right">{number.format(period.orders)}</td>
                      <td className="align-right">{number.format(period.customers)}</td>
                      <td className="align-right">{number.format(period.completed)}</td>
                      <td className="align-right">{number.format(period.cancelled)}</td>
                      <td className="align-right">{number.format(period.open)}</td>
                      <td className="align-right">{currency.format(period.sub_total)}</td>
                      <td className="align-right">{currency.format(period.shipping)}</td>
                      <td className="align-right">{currency.format(period.coupon)}</td>
                      <td className="align-right">{currency.format(period.taxes)}</td>
                      <td className="align-right"><strong>{currency.format(period.total_value)}</strong></td>
                      <td className="align-right">{currency.format(period.average_order_value)}</td>
                      <td className="align-right">{number.format(period.completion_rate)}%</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <section className="panel">
            <div className="panel-title">
              <h2>Status comparison</h2>
              <span>{number.format(statusComparison.length)} visible statuses</span>
            </div>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Status</th>
                    {analytics.periods.map((period) => <th className="align-right" key={period.key}>{period.label}</th>)}
                  </tr>
                </thead>
                <tbody>
                  {statusComparison.length ? statusComparison.map((row) => (
                    <tr key={row.status}>
                      <td><strong>{row.status}</strong></td>
                      {row.values.map((value, index) => <td className="align-right" key={analytics.periods[index].key}>{number.format(value)}</td>)}
                    </tr>
                  )) : (
                    <tr><td className="empty-cell" colSpan={analytics.periods.length + 1}>No selected statuses in these periods.</td></tr>
                  )}
                </tbody>
              </table>
            </div>
          </section>

          <section className="panel">
            <div className="panel-title">
              <div>
                <h2>Time in current status</h2>
                <span>Current OpenCart status across all synced orders.</span>
              </div>
              <CalendarRange size={19} />
            </div>
            <DataTable rows={analytics.status_aging} columns={agingColumns} empty="No current orders match the aging statuses." />
          </section>

          <section className="panel">
            <div className="panel-title">
              <div>
                <h2>Orders waiting in status</h2>
                <span>{number.format(analytics.stale_orders_total)} orders; showing up to 500 oldest.</span>
              </div>
            </div>
            <DataTable rows={analytics.stale_orders} columns={staleColumns} empty={`No orders have remained in a selected status for ${appliedStaleDays} days.`} />
          </section>
        </>
      ) : null}

      {loading ? <div className="loading-overlay"><RefreshCw size={16} /> Loading order analytics...</div> : null}
    </div>
  );
}
