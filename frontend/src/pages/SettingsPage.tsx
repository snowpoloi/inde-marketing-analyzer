import { useEffect, useState } from "react";
import { Save } from "lucide-react";
import { api, IntegrationSetting } from "../api/client";

const placeholders: Record<string, Record<string, unknown>> = {
  meta_ads: {
    ad_account_id: "act_123456789",
    access_token: "read-only-token",
    graph_version: "v20.0"
  },
  google_ads: {
    developer_token: "...",
    client_id: "...apps.googleusercontent.com",
    client_secret: "...",
    refresh_token: "...",
    login_customer_id: "optional-manager-id",
    customer_id: "1234567890"
  },
  ga4: {
    property_id: "123456789",
    service_account_json: {}
  },
  merchant_center: {
    csv_url: "https://..."
  },
  opencart: {
    endpoint_url: "https://inde.gr/index.php?route=api/marketing_analyzer/orders",
    api_key: "optional-token"
  },
  shoply: {
    api_url: "https://...",
    api_key: "optional-token"
  }
};

export function SettingsPage() {
  const [items, setItems] = useState<IntegrationSetting[]>([]);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [message, setMessage] = useState("");

  async function load() {
    const result = await api.integrations();
    setItems(result);
    setDrafts(Object.fromEntries(result.map((item) => [item.provider, JSON.stringify(item.config || {}, null, 2)])));
  }

  useEffect(() => {
    load().catch((err) => setMessage(err instanceof Error ? err.message : "Could not load settings"));
  }, []);

  async function save(item: IntegrationSetting) {
    setMessage("");
    try {
      const config = JSON.parse(drafts[item.provider] || "{}");
      await api.saveIntegration(item.provider, { is_enabled: item.is_enabled, config });
      setMessage(`${item.display_name} saved.`);
      await load();
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Could not save integration");
    }
  }

  function toggle(provider: string) {
    setItems((current) =>
      current.map((item) => (item.provider === provider ? { ...item, is_enabled: !item.is_enabled } : item))
    );
  }

  return (
    <div className="page-stack">
      <header className="page-header">
        <div>
          <h1>Settings</h1>
          <p>Credentials and endpoints for read-only reporting sync.</p>
        </div>
      </header>
      {message ? <div className="notice">{message}</div> : null}
      <section className="settings-grid">
        {items.map((item) => (
          <article className="settings-panel" key={item.provider}>
            <div className="settings-title">
              <div>
                <h2>{item.display_name}</h2>
                <span>{item.provider}</span>
              </div>
              <label className="switch">
                <input type="checkbox" checked={item.is_enabled} onChange={() => toggle(item.provider)} />
                <span />
              </label>
            </div>
            <textarea
              value={drafts[item.provider] ?? ""}
              onChange={(event) => setDrafts((current) => ({ ...current, [item.provider]: event.target.value }))}
              placeholder={JSON.stringify(placeholders[item.provider] ?? {}, null, 2)}
              spellCheck={false}
            />
            <button className="primary-action compact" onClick={() => save(item)}>
              <Save size={17} />
              Save
            </button>
          </article>
        ))}
      </section>
    </div>
  );
}

