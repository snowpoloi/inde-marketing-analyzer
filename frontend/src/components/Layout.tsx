import { BarChart3, FileClock, LogOut, Settings, Store } from "lucide-react";
import type { ReactNode } from "react";

type View = "dashboard" | "settings" | "sync";

export function Layout({
  active,
  onNavigate,
  onLogout,
  children
}: {
  active: View;
  onNavigate: (view: View) => void;
  onLogout: () => void;
  children: ReactNode;
}) {
  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand-mark">
          <Store size={22} />
          <div>
            <strong>INDE</strong>
            <span>Marketing Analyzer</span>
          </div>
        </div>
        <nav>
          <button className={active === "dashboard" ? "active" : ""} onClick={() => onNavigate("dashboard")}>
            <BarChart3 size={18} />
            Dashboard
          </button>
          <button className={active === "settings" ? "active" : ""} onClick={() => onNavigate("settings")}>
            <Settings size={18} />
            Settings
          </button>
          <button className={active === "sync" ? "active" : ""} onClick={() => onNavigate("sync")}>
            <FileClock size={18} />
            Sync logs
          </button>
        </nav>
        <button className="logout" onClick={onLogout}>
          <LogOut size={18} />
          Logout
        </button>
      </aside>
      <main className="content">{children}</main>
    </div>
  );
}
