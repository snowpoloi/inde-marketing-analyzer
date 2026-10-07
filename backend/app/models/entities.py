from datetime import date, datetime
from decimal import Decimal
from uuid import UUID as PyUUID, uuid4

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[PyUUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class IntegrationSetting(TimestampMixin, Base):
    __tablename__ = "integration_settings"
    __table_args__ = (UniqueConstraint("provider", name="uq_integration_settings_provider"),)

    id: Mapped[PyUUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    provider: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    config: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class SyncRun(TimestampMixin, Base):
    __tablename__ = "sync_runs"

    id: Mapped[PyUUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    provider: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    sync_type: Mapped[str] = mapped_column(String(32), nullable=False, default="manual")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="running")
    date_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    date_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    records_processed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    meta: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class CampaignDailyMetric(TimestampMixin, Base):
    __tablename__ = "campaign_daily_metrics"

    id: Mapped[PyUUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    source: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    metric_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    campaign_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    campaign_name: Mapped[str] = mapped_column(String(255), nullable=False)
    campaign_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    adset_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    adset_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ad_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    ad_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    cost: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=0, nullable=False)
    clicks: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    impressions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    conversions: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=0, nullable=False)
    conversion_value: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=0, nullable=False)
    purchases: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=0, nullable=False)
    purchase_value: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=0, nullable=False)
    reach: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    frequency: Mapped[Decimal] = mapped_column(Numeric(10, 4), default=0, nullable=False)
    link_clicks: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    landing_page_views: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    add_to_cart: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    initiate_checkout: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cpc: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=0, nullable=False)
    cpm: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=0, nullable=False)
    ctr: Mapped[Decimal] = mapped_column(Numeric(10, 4), default=0, nullable=False)
    avg_cpc: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=0, nullable=False)
    cost_per_conversion: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=0, nullable=False)
    raw: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class GA4DailyMetric(TimestampMixin, Base):
    __tablename__ = "ga4_daily_metrics"

    id: Mapped[PyUUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    metric_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    channel_group: Mapped[str | None] = mapped_column(String(160), nullable=True)
    source_medium: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sessions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    users: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    purchases: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=0, nullable=False)
    purchase_revenue: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=0, nullable=False)
    conversions: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=0, nullable=False)
    raw: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class MerchantProductMetric(TimestampMixin, Base):
    __tablename__ = "merchant_product_metrics"

    id: Mapped[PyUUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    metric_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    item_id: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    brand: Mapped[str | None] = mapped_column(String(255), nullable=True)
    category: Mapped[str | None] = mapped_column(String(500), nullable=True)
    availability: Mapped[str | None] = mapped_column(String(80), nullable=True)
    price: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=0, nullable=False)
    sale_price: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=0, nullable=False)
    clicks: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    impressions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    ctr: Mapped[Decimal] = mapped_column(Numeric(10, 4), default=0, nullable=False)
    raw: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class SearchConsoleDailyMetric(TimestampMixin, Base):
    __tablename__ = "search_console_daily_metrics"

    id: Mapped[PyUUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    metric_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    site_url: Mapped[str] = mapped_column(String(500), nullable=False, index=True)
    query: Mapped[str | None] = mapped_column(String(500), nullable=True, index=True)
    page: Mapped[str | None] = mapped_column(Text, nullable=True)
    country: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    device: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    clicks: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    impressions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    ctr: Mapped[Decimal] = mapped_column(Numeric(10, 4), default=0, nullable=False)
    position: Mapped[Decimal] = mapped_column(Numeric(10, 4), default=0, nullable=False)
    raw: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class AADEDocument(TimestampMixin, Base):
    __tablename__ = "aade_documents"
    __table_args__ = (UniqueConstraint("identity_key", name="uq_aade_documents_identity_key"),)

    id: Mapped[PyUUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    source_endpoint: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    identity_key: Mapped[str] = mapped_column(String(700), nullable=False, index=True)
    mark: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    uid: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    issuer_vat: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    counterpart_vat: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    issue_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    document_direction: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    invoice_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    series: Mapped[str | None] = mapped_column(String(64), nullable=True)
    aa: Mapped[str | None] = mapped_column(String(64), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(8), nullable=True)
    net_value: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=0, nullable=False)
    vat_amount: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=0, nullable=False)
    gross_value: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=0, nullable=False)
    is_cancelled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    cancelled_by_mark: Mapped[str | None] = mapped_column(String(128), nullable=True)
    raw: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class AADESummaryMetric(TimestampMixin, Base):
    __tablename__ = "aade_summary_metrics"
    __table_args__ = (
        UniqueConstraint("metric_date", "source_endpoint", "metric_name", name="uq_aade_summary_metrics_day_source_name"),
    )

    id: Mapped[PyUUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    metric_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    source_endpoint: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    metric_name: Mapped[str] = mapped_column(String(128), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=0, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    raw: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class BankTransaction(TimestampMixin, Base):
    __tablename__ = "bank_transactions"
    __table_args__ = (UniqueConstraint("source_key", name="uq_bank_transactions_source_key"),)

    id: Mapped[PyUUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    bank_name: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    account: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    transaction_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    value_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    counterparty: Mapped[str | None] = mapped_column(String(500), nullable=True, index=True)
    reference: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=0, nullable=False)
    debit: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=0, nullable=False)
    credit: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=0, nullable=False)
    balance: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(8), nullable=True)
    category: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    transaction_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    source_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    source_key: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    raw: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class OpenCartOrder(TimestampMixin, Base):
    __tablename__ = "opencart_orders"
    __table_args__ = (UniqueConstraint("order_id", name="uq_opencart_orders_order_id"),)

    id: Mapped[PyUUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    order_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    date_added: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    date_modified: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    order_status_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    order_status: Mapped[str | None] = mapped_column(String(120), nullable=True)
    store_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    store_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    customer_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    customer_group_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    customer_group: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    sub_total: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=0, nullable=False)
    tax: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=0, nullable=False)
    total: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=0, nullable=False)
    shipping: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=0, nullable=False)
    payment_method: Mapped[str | None] = mapped_column(String(255), nullable=True)
    payment_code: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    shipping_title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    shipping_method: Mapped[str | None] = mapped_column(String(255), nullable=True)
    shipping_code: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    tracking_carrier: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    payment_country: Mapped[str | None] = mapped_column(String(120), nullable=True)
    payment_zone: Mapped[str | None] = mapped_column(String(120), nullable=True)
    payment_city: Mapped[str | None] = mapped_column(String(160), nullable=True)
    payment_postcode: Mapped[str | None] = mapped_column(String(40), nullable=True)
    shipping_country: Mapped[str | None] = mapped_column(String(120), nullable=True)
    shipping_zone: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    shipping_city: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    shipping_postcode: Mapped[str | None] = mapped_column(String(40), nullable=True)
    currency_code: Mapped[str | None] = mapped_column(String(12), nullable=True)
    raw: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    products: Mapped[list["OpenCartOrderProduct"]] = relationship(
        back_populates="order", cascade="all, delete-orphan", passive_deletes=True
    )
    changes: Mapped[list["OpenCartOrderChange"]] = relationship(
        back_populates="order", cascade="all, delete-orphan", passive_deletes=True
    )


class OpenCartOrderChange(TimestampMixin, Base):
    __tablename__ = "opencart_order_changes"

    id: Mapped[PyUUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    order_pk: Mapped[PyUUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("opencart_orders.id", ondelete="CASCADE"))
    order_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    field_name: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    old_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_modified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    raw: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    order: Mapped[OpenCartOrder] = relationship(back_populates="changes")


class OpenCartOrderProduct(TimestampMixin, Base):
    __tablename__ = "opencart_order_products"

    id: Mapped[PyUUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    order_pk: Mapped[PyUUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("opencart_orders.id", ondelete="CASCADE"))
    product_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sku: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    manufacturer: Mapped[str | None] = mapped_column(String(255), nullable=True)
    brand: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    category: Mapped[str | None] = mapped_column(String(500), nullable=True, index=True)
    quantity: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=0, nullable=False)
    line_subtotal: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=0, nullable=False)
    discount: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=0, nullable=False)
    tax: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=0, nullable=False)
    total: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=0, nullable=False)
    raw: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    order: Mapped[OpenCartOrder] = relationship(back_populates="products")


class ProductCatalog(TimestampMixin, Base):
    __tablename__ = "product_catalog"
    __table_args__ = (UniqueConstraint("sku", name="uq_product_catalog_sku"),)

    id: Mapped[PyUUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    sku: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    model: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    product_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    ean: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    upc: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    mpn: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    brand: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    manufacturer: Mapped[str | None] = mapped_column(String(255), nullable=True)
    category: Mapped[str | None] = mapped_column(String(500), nullable=True, index=True)
    category_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    status: Mapped[str | None] = mapped_column(String(120), nullable=True)
    quantity: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=0, nullable=False)
    link: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class SupplierCatalogFeed(TimestampMixin, Base):
    __tablename__ = "supplier_catalog_feeds"

    id: Mapped[PyUUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    code: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    adapter: Mapped[str] = mapped_column(String(32), nullable=False)
    encrypted_url: Mapped[str] = mapped_column(Text, nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    refresh_hours: Mapped[int] = mapped_column(Integer, default=24, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="idle", nullable=False)
    requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    counts: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class SupplierCatalogProduct(TimestampMixin, Base):
    __tablename__ = "supplier_catalog_products"
    __table_args__ = (UniqueConstraint("feed_id", "supplier_code", name="uq_supplier_catalog_product_identity"),)

    id: Mapped[PyUUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    feed_id: Mapped[PyUUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("supplier_catalog_feeds.id", ondelete="CASCADE"), nullable=False, index=True)
    supplier_code: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    supplier_sku: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    ean: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    category: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    image_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    quantity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    wholesale_price_net: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)
    retail_price_gross: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)
    product_catalog_id: Mapped[PyUUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("product_catalog.id", ondelete="SET NULL"), nullable=True, index=True)
    match_method: Mapped[str] = mapped_column(String(64), default="unmatched", nullable=False)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    details: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class Supplier(TimestampMixin, Base):
    __tablename__ = "suppliers"
    __table_args__ = (UniqueConstraint("code", name="uq_suppliers_code"),)

    id: Mapped[PyUUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    code: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    vat_number: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    aliases: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    default_currency: Mapped[str] = mapped_column(String(8), default="EUR", nullable=False)
    free_shipping_threshold: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)
    payment_terms_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    raw_metadata: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class SupplierImportBatch(TimestampMixin, Base):
    __tablename__ = "supplier_import_batches"
    __table_args__ = (UniqueConstraint("content_hash", name="uq_supplier_import_batches_content_hash"),)

    id: Mapped[PyUUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    supplier_id: Mapped[PyUUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("suppliers.id", ondelete="SET NULL"), nullable=True, index=True
    )
    source_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    source_reference: Mapped[str | None] = mapped_column(String(500), nullable=True)
    filename: Mapped[str | None] = mapped_column(String(500), nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), default="completed", nullable=False, index=True)
    imported_documents: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    raw_metadata: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class SupplierDocument(TimestampMixin, Base):
    __tablename__ = "supplier_documents"
    __table_args__ = (UniqueConstraint("identity_key", name="uq_supplier_documents_identity_key"),)

    id: Mapped[PyUUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    supplier_id: Mapped[PyUUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("suppliers.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    import_batch_id: Mapped[PyUUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("supplier_import_batches.id", ondelete="SET NULL"), nullable=True, index=True
    )
    aade_document_id: Mapped[PyUUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("aade_documents.id", ondelete="SET NULL"), nullable=True, index=True
    )
    identity_key: Mapped[str] = mapped_column(String(700), nullable=False, index=True)
    document_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    document_number: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    document_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    supplier_order_id: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    currency: Mapped[str] = mapped_column(String(8), default="EUR", nullable=False)
    net_products_total: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=0, nullable=False)
    net_shipping_total: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=0, nullable=False)
    net_other_total: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=0, nullable=False)
    vat_total: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=0, nullable=False)
    gross_total: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=0, nullable=False)
    raw_metadata: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class SupplierProductMap(TimestampMixin, Base):
    __tablename__ = "supplier_product_maps"
    __table_args__ = (
        UniqueConstraint("supplier_id", "identity_key", name="uq_supplier_product_maps_supplier_identity"),
    )

    id: Mapped[PyUUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    supplier_id: Mapped[PyUUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("suppliers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    product_catalog_id: Mapped[PyUUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("product_catalog.id", ondelete="SET NULL"), nullable=True, index=True
    )
    identity_key: Mapped[str] = mapped_column(String(700), nullable=False)
    supplier_code: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    supplier_sku: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    supplier_ean: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    opencart_product_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    opencart_sku: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    opencart_model: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    product_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    purchase_unit: Mapped[str | None] = mapped_column(String(32), nullable=True)
    sales_unit: Mapped[str | None] = mapped_column(String(32), nullable=True)
    pack_quantity: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=1, nullable=False)
    conversion_factor: Mapped[Decimal] = mapped_column(Numeric(14, 6), default=1, nullable=False)
    match_method: Mapped[str] = mapped_column(String(64), default="unmatched", nullable=False, index=True)
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4), default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="unmatched", nullable=False, index=True)
    verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    verified_by: Mapped[PyUUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    raw_metadata: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class SupplierDocumentLine(TimestampMixin, Base):
    __tablename__ = "supplier_document_lines"
    __table_args__ = (UniqueConstraint("document_id", "line_number", name="uq_supplier_document_lines_number"),)

    id: Mapped[PyUUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    document_id: Mapped[PyUUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("supplier_documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    supplier_product_map_id: Mapped[PyUUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("supplier_product_maps.id", ondelete="SET NULL"), nullable=True, index=True
    )
    line_number: Mapped[str] = mapped_column(String(64), nullable=False)
    line_type: Mapped[str] = mapped_column(String(32), default="product", nullable=False, index=True)
    supplier_code: Mapped[str | None] = mapped_column(String(255), nullable=True)
    supplier_sku: Mapped[str | None] = mapped_column(String(255), nullable=True)
    supplier_ean: Mapped[str | None] = mapped_column(String(64), nullable=True)
    description: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=0, nullable=False)
    unit: Mapped[str | None] = mapped_column(String(32), nullable=True)
    unit_price_before_discount: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=0, nullable=False)
    discount_percent: Mapped[Decimal] = mapped_column(Numeric(8, 4), default=0, nullable=False)
    discount_amount: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=0, nullable=False)
    net_unit_cost: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=0, nullable=False)
    net_line_total: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=0, nullable=False)
    vat_rate: Mapped[Decimal] = mapped_column(Numeric(8, 4), default=0, nullable=False)
    vat_amount: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=0, nullable=False)
    gross_total: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=0, nullable=False)
    raw_metadata: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class SupplierProductCost(TimestampMixin, Base):
    __tablename__ = "supplier_product_costs"
    __table_args__ = (UniqueConstraint("source_key", name="uq_supplier_product_costs_source_key"),)

    id: Mapped[PyUUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    supplier_id: Mapped[PyUUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("suppliers.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    supplier_product_map_id: Mapped[PyUUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("supplier_product_maps.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    product_catalog_id: Mapped[PyUUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("product_catalog.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    source_line_id: Mapped[PyUUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("supplier_document_lines.id", ondelete="SET NULL"), nullable=True, index=True
    )
    supplier_sku: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    source_reference: Mapped[str | None] = mapped_column(String(500), nullable=True)
    source_key: Mapped[str] = mapped_column(String(700), nullable=False, index=True)
    supplier_order_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    supplier_invoice_number: Mapped[str | None] = mapped_column(String(160), nullable=True)
    purchase_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=0, nullable=False)
    unit_price_before_discount: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=0, nullable=False)
    discount_percent: Mapped[Decimal] = mapped_column(Numeric(8, 4), default=0, nullable=False)
    net_unit_cost: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=0, nullable=False)
    net_line_total: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=0, nullable=False)
    vat: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=0, nullable=False)
    gross_total: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=0, nullable=False)
    currency: Mapped[str] = mapped_column(String(8), default="EUR", nullable=False)
    source_confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4), default=1, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False, index=True)
    raw_metadata: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class SupplierShippingCost(TimestampMixin, Base):
    __tablename__ = "supplier_shipping_costs"
    __table_args__ = (UniqueConstraint("source_key", name="uq_supplier_shipping_costs_source_key"),)

    id: Mapped[PyUUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    supplier_id: Mapped[PyUUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("suppliers.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    document_id: Mapped[PyUUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("supplier_documents.id", ondelete="SET NULL"), nullable=True, index=True
    )
    source_line_id: Mapped[PyUUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("supplier_document_lines.id", ondelete="SET NULL"), nullable=True
    )
    source_key: Mapped[str] = mapped_column(String(700), nullable=False, index=True)
    supplier_order_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    invoice_reference: Mapped[str | None] = mapped_column(String(160), nullable=True)
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    shipping_type: Mapped[str] = mapped_column(String(32), default="INBOUND", nullable=False, index=True)
    net_shipping_cost: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=0, nullable=False)
    vat: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=0, nullable=False)
    gross_shipping_cost: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=0, nullable=False)
    order_net_purchase_value: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=0, nullable=False)
    cbm: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)
    weight: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_metadata: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class SupplierGmailSource(TimestampMixin, Base):
    __tablename__ = "supplier_gmail_sources"
    __table_args__ = (UniqueConstraint("source_key", name="uq_supplier_gmail_sources_source_key"),)

    id: Mapped[PyUUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    mailbox: Mapped[str] = mapped_column(String(255), nullable=False)
    message_id: Mapped[str] = mapped_column(String(128), nullable=False)
    part_id: Mapped[str] = mapped_column(String(128), nullable=False)
    attachment_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    filename: Mapped[str | None] = mapped_column(String(500), nullable=True)
    source_key: Mapped[str] = mapped_column(String(64), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    semantic_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    normalized_payload: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    duplicate_of_id: Mapped[PyUUID | None] = mapped_column(PG_UUID(as_uuid=True),
        ForeignKey("supplier_gmail_sources.id", ondelete="SET NULL"), nullable=True)
    import_batch_id: Mapped[PyUUID | None] = mapped_column(PG_UUID(as_uuid=True),
        ForeignKey("supplier_import_batches.id", ondelete="SET NULL"), nullable=True)
    reviewed_by: Mapped[PyUUID | None] = mapped_column(PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SupplierGmailJob(TimestampMixin, Base):
    __tablename__ = "supplier_gmail_jobs"

    id: Mapped[PyUUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    mode: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="queued", nullable=False, index=True)
    date_from: Mapped[date] = mapped_column(Date, nullable=False)
    date_to: Mapped[date] = mapped_column(Date, nullable=False)
    page_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    completed_message_ids: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    counts: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    pages: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ShoplySale(TimestampMixin, Base):
    __tablename__ = "shoply_sales"

    id: Mapped[PyUUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    external_order_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    sale_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    status: Mapped[str | None] = mapped_column(String(120), nullable=True)
    total: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=0, nullable=False)
    raw: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class CampaignRecommendation(TimestampMixin, Base):
    __tablename__ = "campaign_recommendations"

    id: Mapped[PyUUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    recommendation_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    campaign_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    campaign_name: Mapped[str] = mapped_column(String(255), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    metrics: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
