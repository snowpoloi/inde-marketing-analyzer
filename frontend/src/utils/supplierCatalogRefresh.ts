import type { SupplierCatalogRefresh } from "../api/client";

export function catalogDataChanged(previous: SupplierCatalogRefresh, next: SupplierCatalogRefresh, feedId: string): boolean {
  if (previous.sync_revision !== next.sync_revision) return true;
  const ids = new Set([...previous.feeds, ...next.feeds].filter(feed => !feedId || feed.id === feedId).map(feed => feed.id));
  if (!feedId) {
    for (const id of [...Object.keys(previous.cost_revisions), ...Object.keys(next.cost_revisions)]) ids.add(id);
  }
  return [...ids].some(id => previous.feeds.find(feed => feed.id === id)?.last_synced_at !== next.feeds.find(feed => feed.id === id)?.last_synced_at
    || previous.cost_revisions[id] !== next.cost_revisions[id]);
}
