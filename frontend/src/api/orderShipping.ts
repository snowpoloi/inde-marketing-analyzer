export type ShippingValue = number | string | null;
export type ShippingParcel = {
  key: string; label: string; width_cm: ShippingValue; length_cm: ShippingValue;
  height_cm: ShippingValue; weight_kg: ShippingValue;
};
export type ShippingTariff = {
  version: string; valid_from: string; valid_to: string | null;
  max_side_cm: ShippingValue; max_sum_cm: ShippingValue;
  zones: Array<{code: string; label: string}>;
};
export type ShippingSettings = {
  configured: boolean; origin?: string; vat_percent?: ShippingValue; volumetric_divisor?: number;
  mytrans?: ShippingTariff; speedex?: ShippingTariff; mytrans_area_rows?: number;
  speedex_area_rows?: number; mytrans_area_source?: string; speedex_area_source?: string;
};
export type ShippingContext = {
  order_id: string; shipping_date: string; origin: string; currency: string;
  destination: {country: string | null; region: string | null; city: string | null; postcode: string | null};
  order_shipping: ShippingValue; order_total: ShippingValue; payment_method: string | null;
  settings: ShippingSettings; parcels: ShippingParcel[]; warnings: string[];
  defaults: Partial<ShippingInputs>; matched_fields: Partial<Record<keyof ShippingInputs, string>>;
  mytrans_areas: null | {exact_locality: boolean; rows: Array<{
    postcode: string; locality: string; municipality: string; status: string; extra_net: ShippingValue;
  }>};
};
export type ShippingInputs = {
  shipping_date: string; manifest_confirmed: boolean; mytrans_zone: string; speedex_zone: string;
  mytrans_area_confirmed: boolean; mytrans_remote_extra: ShippingValue;
  mytrans_cod_allowed: boolean | null; mytrans_local_cod: boolean | null; small_pickup: false;
  speedex_remote: boolean | null; saturday: boolean; timed: boolean; cod: boolean | null;
  cod_amount: ShippingValue; speedex_cod_parcels: number | null; customer_shipping_net: ShippingValue;
};
export type ShippingResult = {
  order_id: string; shipping_date: string; kind: string; carriers: Array<{
    carrier: string; tariff_version: string; status: string; issues: string[]; warnings: string[];
    parcels: Array<{key: string; volume_m3: ShippingValue; volumetric_kg: ShippingValue;
      billable_kg: ShippingValue; base_net: ShippingValue}>;
    charges: Array<{label: string; net: ShippingValue}>;
    net: ShippingValue; vat: ShippingValue; gross: ShippingValue; shipping_balance_net: ShippingValue;
  }>;
};
