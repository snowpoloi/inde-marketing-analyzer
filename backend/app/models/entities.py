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
    raw: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    order: Mapped[OpenCartOrder] = relationship(back_populates="products")


class ProductCatalog(TimestampMixin, Base):
    __tablename__ = "product_catalog"
    __table_args__ = (UniqueConstraint("sku", name="uq_product_catalog_sku"),)

    id: Mapped[PyUUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    sku: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    model: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    product_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
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
