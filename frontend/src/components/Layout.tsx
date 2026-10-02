import {
  Banknote,
  BarChart3,
  FileClock,
  Landmark,
  ListChecks,
  LogOut,
  PackageSearch,
  SearchCheck,
  Settings,
  ShoppingCart,
  Store,
  Warehouse
} from "lucide-react";
import type { ReactNode } from "react";

type View = "dashboard" | "audit" | "aade" | "banks" | "orders" | "order-analytics" | "products" | "suppliers" | "settings" | "sync";

export function Layout({
  active,
  onNavigate,
  onLogout,
  isAdmin,
  children
}: {
  active: View;
  onNavigate: (view: View) => void;
  onLogout: () => void;
  isAdmin: boolean;
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
          <button className={active === "audit" ? "active" : ""} onClick={() => onNavigate("audit")}>
            <SearchCheck size={18} />
            Audit
          </button>
          <button className={active === "aade" ? "active" : ""} onClick={() => onNavigate("aade")}>
            <Landmark size={18} />
            AADE
          </button>
          <button className={active === "banks" ? "active" : ""} onClick={() => onNavigate("banks")}>
            <Banknote size={18} />
            Banks
          </button>
          <button className={active === "orders" ? "active" : ""} onClick={() => onNavigate("orders")}>
            <ShoppingCart size={18} />
            Orders
          </button>
          <button className={active === "order-analytics" ? "active" : ""} onClick={() => onNavigate("order-analytics")}>
            <ListChecks size={18} />
            Order analytics
          </button>
          <button className={active === "products" ? "active" : ""} onClick={() => onNavigate("products")}>
            <PackageSearch size={18} />
            Products
          </button>
          {isAdmin ? <button title="Suppliers & COGS" className={active === "suppliers" ? "active" : ""} onClick={() => onNavigate("suppliers")}>
            <Warehouse size={18} />
            Suppliers &amp; COGS
          </button> : null}
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
