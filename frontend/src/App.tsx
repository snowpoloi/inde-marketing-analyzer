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
import { SupplierCatalogPage } from "./pages/SupplierCatalogPage";
import { SettingsPage } from "./pages/SettingsPage";
import { SyncLogsPage } from "./pages/SyncLogsPage";
import { SuppliersPage } from "./pages/SuppliersPage";
import { TikTokCallbackPage } from "./pages/TikTokCallbackPage";
import { RecordDetailPage } from "./pages/RecordDetailPage";

type View = "dashboard" | "audit" | "aade" | "banks" | "orders" | "order-analytics" | "products" | "supplier-catalog" | "suppliers" | "settings" | "sync";

function hashToView(): View {
  const hash = window.location.hash.replace("#", "").split("/")[0];
  if (
    hash === "audit" ||
    hash === "aade" ||
    hash === "banks" ||
    hash === "orders" ||
    hash === "order-analytics" ||
    hash === "products" ||
    hash === "supplier-catalog" ||
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
  const [recordHash, setRecordHash] = useState(window.location.hash);
  useEffect(()=>{
    const update=()=>{setView(hashToView());setRecordHash(window.location.hash);};
    window.addEventListener("hashchange",update);
    return ()=>window.removeEventListener("hashchange",update);
  },[]);
  const recordMatch = /^#(aade\/document|orders\/order)\/([^/]+)$/.exec(recordHash);

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
    setRecordHash(window.location.hash);
    window.scrollTo({ top: 0, behavior: "instant" });
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
      {recordMatch ? <RecordDetailPage kind={view === "aade" ? "invoice" : "order"} id={recordMatch[2]} onBack={()=>navigate(view)}/> : null}
      {view === "aade" && !recordMatch ? <AadePage /> : null}
      {view === "banks" ? <BanksPage /> : null}
      {view === "orders" && !recordMatch ? <OrdersPage /> : null}
      {view === "order-analytics" ? <OrderAnalyticsPage /> : null}
      {view === "products" ? <ProductsPage /> : null}
      {view === "supplier-catalog" ? (isAdmin ? <SupplierCatalogPage /> : <div className="notice">Admin access required.</div>) : null}
      {view === "suppliers" ? (isAdmin ? <SuppliersPage onSettings={() => navigate("settings")} /> : <div className="notice">Admin access required.</div>) : null}
      {view === "settings" ? <SettingsPage /> : null}
      {view === "sync" ? <SyncLogsPage /> : null}
    </Layout>
  );
}
