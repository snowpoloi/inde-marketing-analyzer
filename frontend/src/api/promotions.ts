export type PromotionProduct = {
  id: string; sku: string; name: string; brand: string | null; category: string | null;
  stock: number; price_gross: number; image_url: string | null; link: string | null;
  margin_percent: number | null; cost_date: string | null; last_seen_at: string;
  orders: number; sold_quantity: number; eligible: boolean; reasons: string[];
};
export type PromotionFormat = "9:16" | "16:9" | "1:1";
export type PromotionInput = {
  title: string; product_ids: string[]; date_from: string; date_to: string;
  style: "cinematic" | "editorial" | "detail"; formats: PromotionFormat[];
  duration: 15 | 30; hook: string; cta: string; notes: string;
};
export type PromotionBrief = {
  parameters: PromotionInput;
  products: Array<{id:string; sku:string; name:string; image_url:string; link:string; price_gross:number; stock_at_selection:number}>;
  variants: Array<{aspect_ratio:PromotionFormat; width:number; height:number; channels:string[];
    shots:Array<{sku:string;image_url:string;seconds:number;prompt:string}>; end_card_text:string[]; end_card_seconds:number}>;
  ad_links: Record<"google"|"meta"|"tiktok",string>;
  storyboard: Array<{time:string;label:string;copy:string}>;
};
export type PromotionAsset = {id:string; aspect_ratio:PromotionFormat; filename:string; byte_size:number;
  status:string; review:Record<string,unknown>};
export type PromotionCampaignSummary = {id:string; title:string; status:string; created_at:string};
export type PromotionCampaign = PromotionCampaignSummary & {updated_at:string; brief:PromotionBrief; assets:PromotionAsset[]};
export type PromotionReview = {product_identity:boolean; cta_and_text:boolean; image_and_audio_rights:boolean; platform_format:boolean};
