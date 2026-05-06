import { useEffect, useState } from "react";
import { api, clearToken } from "./api/client";
import { Layout } from "./components/Layout";
import { DashboardPage } from "./pages/DashboardPage";
import { LoginPage } from "./pages/LoginPage";
import { SettingsPage } from "./pages/SettingsPage";
import { SyncLogsPage } from "./pages/SyncLogsPage";

type View = "dashboard" | "settings" | "sync";

function hashToView(): View {
  const hash = window.location.hash.replace("#", "");
  if (hash === "settings" || hash === "sync") {
    return hash;
  }
  return "dashboard";
}

export function App() {
  const [authenticated, setAuthenticated] = useState(Boolean(localStorage.getItem("inde_token")));
  const [view, setView] = useState<View>(hashToView());

  useEffect(() => {
    if (!authenticated) {
      return;
    }
    api.me().catch(() => {
      clearToken();
      setAuthenticated(false);
    });
  }, [authenticated]);

  function navigate(next: View) {
    window.location.hash = next === "dashboard" ? "" : next;
    setView(next);
  }

  if (!authenticated) {
    return <LoginPage onLogin={() => setAuthenticated(true)} />;
  }

  return (
    <Layout
      active={view}
      onNavigate={navigate}
      onLogout={() => {
        clearToken();
        setAuthenticated(false);
      }}
    >
      {view === "dashboard" ? <DashboardPage /> : null}
      {view === "settings" ? <SettingsPage /> : null}
      {view === "sync" ? <SyncLogsPage /> : null}
    </Layout>
  );
}

