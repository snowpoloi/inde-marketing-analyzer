# Promotions

The admin-only `#promotions` workspace prepares product video campaigns and can render
them with local FFmpeg. No generation API, API key, or credits are required. It does not
publish ads or spend advertising budget. Higgsfield remains an optional external workflow.

## Workflow

1. Select up to three real INDE catalog products. Suggested products use the selected
   report period's sales, current catalog stock, and verified latest AADE catalog costs.
   The default minimum gross margin is 18%, calculated on net selling price. Sale pack
   quantities come from the existing supplier mappings; unknown quantities are never
   silently treated as one. Missing or conflicting costs are excluded by default.
2. Choose direction, formats, duration, hook, and CTA; save the campaign in PostgreSQL.
   Products, photos, prices, and source timestamps are snapshotted. No AI has run yet.
3. Open the campaign, choose an aspect ratio and click **Δημιουργία βίντεο**. Choose
   one or two ordered photos from each product's INDE gallery and confirm the VAT-inclusive
   EUR offers read for the exact SKUs. The worker rechecks prices and photo membership
   before rendering. A changed price or a removed selection stops the job.
4. The local render uses INDE plum and white for graphics, a hook with an animated photo
   reveal, product shots with VAT-inclusive prices, and the saved CTA. If two photos
   were selected for a product, the second shot uses the second photo instead of a crop.
   An original instrumental cue accents the cuts; no external music or voice API is
   used. The supplied purple INDE card fills the last three seconds without cropping
   its contents. The MP4 appears for review and download in the campaign.
5. Alternatively, download the preparation ZIP. It contains English shot prompts, reference photo URLs,
   a storyboard, branded final-card PNGs at exact target dimensions, and per-channel INDE UTM
   destinations. It does not contain purchase costs, customer/order records, or secrets.
   Assemble footage externally in Higgsfield and import the finished MP4 (64 MB maximum).
6. Preview each MP4 and explicitly confirm product
   identity, CTA/text, rights and platform format. Approval never publishes a campaign.
   An MP4 cannot navigate to a site by itself: configure the exported URL as the ad's
   destination in Google/YouTube, Meta or TikTok.

## Storage And Safety

- Migration `0014_promotion_render` adds the persisted render queue and confirmed prices.
  `0015_promotion_gallery` stores the ordered photo selections for each job.
  One worker encodes at a time, with a bounded timeout and two encoder threads.
- The renderer reads only public HTTPS INDE product pages and INDE catalog images. It
  checks the SKU, currency, stock and price and validates redirects and image size.
- Every campaign, ZIP, upload, video download and approval requires an admin login and
  ownership of that campaign. One administrator cannot read another's creative assets.
- `PROMOTION_MEDIA_DIR` defaults to `promotion-media` relative to the backend workdir.
  Both Compose files mount `promotion_media` at `/app/promotion-media` for API and worker. Back up this
  volume alongside PostgreSQL; avoid ephemeral container-only storage. The backend
  image installs FFmpeg; for local development, set `PROMOTION_FFMPEG_PATH` if needed.
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
`backend/tests/test_promotion_render.py` covers price matching, redirect restrictions,
authorization, price changes, asset storage and real FFmpeg output for the three ratios.

Official integration references:
- https://higgsfield.ai/blog/higgsfield-api (subscription/API separation)
- https://open.higgsfield.ai/quick-start (server-side API credential/lifecycle guidance)
- https://docs.higgsfield.ai/docs/concepts/billing-and-retention (estimates and retention)
