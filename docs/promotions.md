# Promotions

The admin-only `#promotions` workspace prepares product video campaigns. This first
version uses the owner's **Higgsfield website subscription**. It does not call a paid
generation API, control a browser account, publish ads, or spend advertising budget.
A Higgsfield connection in Codex/ChatGPT is not a credential available to this server.
Fully automatic generation inside this application requires a separate future API
integration and a per-generation estimate/approval flow.

## Workflow

1. Select up to three real INDE catalog products. Suggested products use the selected
   report period's sales, current catalog stock, and verified latest AADE catalog costs.
   The default minimum gross margin is 18%, calculated on net selling price. Sale pack
   quantities come from the existing supplier mappings; unknown quantities are never
   silently treated as one. Missing or conflicting costs are excluded by default.
2. Choose direction, formats, duration, hook, and CTA; save the campaign in PostgreSQL.
   Products, photos, prices, and source timestamps are snapshotted. No AI has run yet.
3. Download the preparation ZIP. It contains English shot prompts, reference photo URLs,
   a storyboard, final CTA PNGs at exact target dimensions, and per-channel INDE UTM
   destinations. It does not contain purchase costs, customer/order records, or secrets.
4. Generate and assemble footage in Higgsfield using the owner's subscription, or use
   an authorized Higgsfield connector separately. Add the supplied end card and real
   typography in the editor; do not trust generated brand text. References/prompts do
   not guarantee visual fidelity. A human must verify the product and licensed audio.
5. Import each finished MP4 (64 MB maximum), preview it, and explicitly confirm product
   identity, CTA/text, rights and platform format. Approval never publishes a campaign.
   An MP4 cannot navigate to a site by itself: configure the exported URL as the ad's
   destination in Google/YouTube, Meta or TikTok.

## Storage And Safety

- Migration `0013_promotions` adds campaigns and video asset metadata; existing reporting
  and sync integrations are unchanged. There is no provider polling or automatic render.
- Every campaign, ZIP, upload, video download and approval requires an admin login and
  ownership of that campaign. One administrator cannot read another's creative assets.
- `PROMOTION_MEDIA_DIR` defaults to `promotion-media` relative to the backend workdir.
  Both Compose files mount `promotion_media` at `/app/promotion-media`. Back up this
  volume alongside PostgreSQL; avoid ephemeral container-only storage.
- Uploads are streamed with a 64 MB limit and an ISO-BMFF file signature check. The
  frontend proxy allows 65 MB on this upload route to include multipart overhead.
  The signature check is not codec/ratio validation or malware scanning. Playback and explicit
  human format review remain required. Uploaded bytes are not run or rendered server-side.
- Paths are generated from asset UUIDs, not uploaded filenames. Identical bytes uploaded
  to the same campaign/format are deduplicated. Replaced versions remain available.
- Changes to stock/prices after saving do not automatically rewrite footage or copy.
  Recheck availability, current price and current platform specifications before posting.

## Verification

`backend/tests/test_promotions.py` covers validation, packed-sale margin calculation,
preservation of product/duration references, ZIP dimensions, authentication, ownership,
video upload checks, deduplication and explicit approval. Use an isolated PostgreSQL
database migrated to head, following `backend/tests/conftest.py`.

Official integration references:
- https://higgsfield.ai/blog/higgsfield-api (subscription/API separation)
- https://open.higgsfield.ai/quick-start (server-side API credential/lifecycle guidance)
- https://docs.higgsfield.ai/docs/concepts/billing-and-retention (estimates and retention)
