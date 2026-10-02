import { useEffect, useState } from "react";
import { api, clearToken } from "./api/client";
import { Layout } from "./components/Layout";
import { AadePage } from "./pages/AadePage";
import { AuditPage } from "./pages/AuditPage";
import { BanksPage } from "./pages/BanksPage";
import { DashboardPage } from "./pages/DashboardPage";
import { LoginPage } from "./pages/LoginPage";
import { OrdersPage } from "./pages/OrdersPage";
import { OrderAnalyticsPage } from "./pages/OrderAnalyticsPage";
import { ProductsPage } from "./pages/ProductsPage";
import { SettingsPage } from "./pages/SettingsPage";
import { SyncLogsPage } from "./pages/SyncLogsPage";
import { SuppliersPage } from "./pages/SuppliersPage";
import { TikTokCallbackPage } from "./pages/TikTokCallbackPage";

type View = "dashboard" | "audit" | "aade" | "banks" | "orders" | "order-analytics" | "products" | "suppliers" | "settings" | "sync";

function hashToView(): View {
  const hash = window.location.hash.replace("#", "");
  if (
    hash === "audit" ||
    hash === "aade" ||
    hash === "banks" ||
    hash === "orders" ||
    hash === "order-analytics" ||
    hash === "products" ||
    hash === "suppliers" ||
    hash === "settings" ||
    hash === "sync"
  ) {
    return hash;
  }
  return "dashboard";
}

export function App() {
  const [authenticated, setAuthenticated] = useState(Boolean(localStorage.getItem("inde_token")));
  const [view, setView] = useState<View>(hashToView());
  const [isAdmin, setIsAdmin] = useState(false);

  useEffect(() => {
    if (!authenticated) {
      return;
    }
    api.me().then((user) => setIsAdmin(user.is_admin)).catch(() => {
      clearToken();
      setAuthenticated(false);
    });
  }, [authenticated]);

  function navigate(next: View) {
    window.location.hash = next === "dashboard" ? "" : next;
    setView(next);
  }

  if (window.location.pathname === "/tiktok/callback") {
    return <TikTokCallbackPage />;
  }

  if (!authenticated) {
    return <LoginPage onLogin={() => setAuthenticated(true)} />;
  }

  return (
    <Layout
      isAdmin={isAdmin}
      active={view}
      onNavigate={navigate}
      onLogout={() => {
        clearToken();
        setAuthenticated(false);
      }}
    >
      {view === "dashboard" ? <DashboardPage /> : null}
      {view === "audit" ? <AuditPage /> : null}
      {view === "aade" ? <AadePage /> : null}
      {view === "banks" ? <BanksPage /> : null}
      {view === "orders" ? <OrdersPage /> : null}
      {view === "order-analytics" ? <OrderAnalyticsPage /> : null}
      {view === "products" ? <ProductsPage /> : null}
      {view === "suppliers" ? (isAdmin ? <SuppliersPage /> : <div className="notice">Admin access required.</div>) : null}
      {view === "settings" ? <SettingsPage /> : null}
      {view === "sync" ? <SyncLogsPage /> : null}
    </Layout>
  );
}
