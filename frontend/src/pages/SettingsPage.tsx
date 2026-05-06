import { useEffect, useState } from "react";
import { Plus, Save, Trash2 } from "lucide-react";
import { api } from "../api/client";
import type { IntegrationSetting } from "../api/client";

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
    endpoint_url: "https://inde.gr/shopor/an.json",
    product_feed_url: "https://inde.gr/index.php?route=feed/universal_feed&feed=findbar.xml",
    api_key: "optional-token",
    timeout_seconds: 60,
    order_status_rules: [
      { name: "Completed", counts_as_sale: true },
      { name: "Replacement", counts_as_sale: false },
      { name: "Cancelled", counts_as_sale: false }
    ]
  },
  shoply: {
    api_url: "https://...",
    api_key: "optional-token"
  }
};

type OrderStatusRule = {
  name: string;
  counts_as_sale: boolean;
};

function parseDraft(text: string | undefined): Record<string, unknown> {
  try {
    const parsed = JSON.parse(text || "{}");
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : {};
  } catch {
    return {};
  }
}

function orderStatusRules(config: Record<string, unknown>): OrderStatusRule[] {
  const rules = config.order_status_rules;
  if (!Array.isArray(rules)) {
    return [];
  }
  return rules.map((rule) => {
    const value = rule as Record<string, unknown>;
    return { name: String(value.name ?? ""), counts_as_sale: Boolean(value.counts_as_sale) };
  });
}

export function SettingsPage() {
  const [items, setItems] = useState<IntegrationSetting[]>([]);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [detectedStatuses, setDetectedStatuses] = useState<string[]>([]);
  const [message, setMessage] = useState("");

  async function load() {
    const [result, statuses] = await Promise.all([api.integrations(), api.opencartOrderStatuses().catch(() => [])]);
    setItems(result);
    setDetectedStatuses(statuses);
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

  function updateOpenCartConfig(patch: Record<string, unknown>) {
    const current = parseDraft(drafts.opencart);
    setDrafts((existing) => ({ ...existing, opencart: JSON.stringify({ ...current, ...patch }, null, 2) }));
  }

  function updateStatusRule(index: number, patch: Partial<OrderStatusRule>) {
    const config = parseDraft(drafts.opencart);
    const rules = orderStatusRules(config);
    rules[index] = { ...rules[index], ...patch };
    updateOpenCartConfig({ order_status_rules: rules });
  }

  function addStatusRule() {
    const config = parseDraft(drafts.opencart);
    updateOpenCartConfig({ order_status_rules: [...orderStatusRules(config), { name: "", counts_as_sale: true }] });
  }

  function addDetectedStatus(name: string) {
    const config = parseDraft(drafts.opencart);
    updateOpenCartConfig({ order_status_rules: [...orderStatusRules(config), { name, counts_as_sale: true }] });
  }

  function removeStatusRule(index: number) {
    const config = parseDraft(drafts.opencart);
    updateOpenCartConfig({ order_status_rules: orderStatusRules(config).filter((_, itemIndex) => itemIndex !== index) });
  }

  function renderOpenCartControls() {
    const config = parseDraft(drafts.opencart);
    const rules = orderStatusRules(config);
    const ruleNames = new Set(rules.map((rule) => rule.name.trim().toLowerCase()));
    const missingDetectedStatuses = detectedStatuses.filter((status) => !ruleNames.has(status.trim().toLowerCase()));
    return (
      <div className="opencart-controls">
        <div className="form-grid">
          <label>
            <span>Orders JSON endpoint</span>
            <input
              value={String(config.endpoint_url ?? "")}
              onChange={(event) => updateOpenCartConfig({ endpoint_url: event.target.value })}
              placeholder="https://inde.gr/shopor/an.json"
            />
          </label>
          <label>
            <span>Product XML feed</span>
            <input
              value={String(config.product_feed_url ?? "")}
              onChange={(event) => updateOpenCartConfig({ product_feed_url: event.target.value })}
              placeholder="https://inde.gr/index.php?route=feed/universal_feed&feed=findbar.xml"
            />
          </label>
          <label>
            <span>Timeout seconds</span>
            <input
              type="number"
              min="10"
              value={String(config.timeout_seconds ?? 60)}
              onChange={(event) => updateOpenCartConfig({ timeout_seconds: Number(event.target.value) || 60 })}
            />
          </label>
          <label>
            <span>API token</span>
            <input
              value={String(config.api_key ?? "")}
              onChange={(event) => updateOpenCartConfig({ api_key: event.target.value })}
              placeholder="optional"
            />
          </label>
        </div>

        <div className="status-rules">
          <div className="panel-title tight">
            <h2>Order status rules</h2>
            <span>Only checked statuses count as actual sales.</span>
          </div>
          {rules.length === 0 ? (
            <p className="helper-text">No rules yet. Until you add rules, all OpenCart orders count as sales.</p>
          ) : null}
          <div className="status-rule-list">
            {rules.map((rule, index) => (
              <div className="status-rule-row" key={index}>
                <input
                  value={rule.name}
                  onChange={(event) => updateStatusRule(index, { name: event.target.value })}
                  placeholder="e.g. Completed"
                />
                <label className="checkbox-label">
                  <input
                    type="checkbox"
                    checked={rule.counts_as_sale}
                    onChange={(event) => updateStatusRule(index, { counts_as_sale: event.target.checked })}
                  />
                  Counts as sale
                </label>
                <button className="icon-button danger" onClick={() => removeStatusRule(index)} aria-label="Remove status">
                  <Trash2 size={16} />
                </button>
              </div>
            ))}
          </div>
          <button className="secondary-action compact" onClick={addStatusRule}>
            <Plus size={16} />
            Add status
          </button>
          {missingDetectedStatuses.length > 0 ? (
            <div className="detected-statuses">
              <span>Detected from OpenCart</span>
              <div>
                {missingDetectedStatuses.map((status) => (
                  <button className="status-chip" key={status} onClick={() => addDetectedStatus(status)}>
                    <Plus size={14} />
                    {status}
                  </button>
                ))}
              </div>
            </div>
          ) : null}
        </div>
      </div>
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
            {item.provider === "opencart" ? renderOpenCartControls() : null}
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
