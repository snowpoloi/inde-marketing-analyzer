import type { LucideIcon } from "lucide-react";

export function StatCard({
  label,
  value,
  detail,
  icon: Icon
}: {
  label: string;
  value: string;
  detail?: string;
  icon: LucideIcon;
}) {
  return (
    <section className="stat-card">
      <div className="stat-icon">
        <Icon size={18} />
      </div>
      <div>
        <p>{label}</p>
        <strong>{value}</strong>
        {detail ? <span>{detail}</span> : null}
      </div>
    </section>
  );
}

