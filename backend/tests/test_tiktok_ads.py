import json
from datetime import date
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import select

from app.connectors.tiktok_ads import TikTokAdsConnector
from app.models import CampaignDailyMetric
from app.services.dashboard_service import source_performance
from app.services.import_service import import_tiktok_ads_csv, import_tiktok_ads_rows


DAY = date(2026, 10, 1)


def test_default_report_requests_website_purchase_metrics():
    connector = TikTokAdsConnector({})
    metrics = json.loads(connector._base_params(DAY, DAY)["metrics"])
    assert "complete_payment" in metrics
    assert "total_complete_payment_rate" in metrics
    assert not any(metric.startswith("onsite_") for metric in metrics)


def test_configured_metrics_cannot_omit_website_purchases_or_mutate_config():
    configured = ["spend", "onsite_total_purchase", "complete_payment"]
    connector = TikTokAdsConnector({"metrics": configured})
    assert connector.metrics.count("complete_payment") == 1
    assert "total_complete_payment_rate" in connector.metrics
    assert configured == ["spend", "onsite_total_purchase", "complete_payment"]


@pytest.mark.parametrize("purchases,value", [("3", "180.50"), (0, 0), ("0", "0"), (None, None)])
def test_normalisation_never_substitutes_other_purchase_types(purchases, value):
    row = {"metrics": {
        "complete_payment": purchases, "total_complete_payment_rate": value,
        "onsite_total_purchase": "99", "onsite_total_purchase_value_day29": "9999",
        "conversion": "88", "total_purchase": "77", "total_purchase_value": "7777",
    }}
    normalized = TikTokAdsConnector._normalise_row(row, DAY)
    assert normalized["purchases"] == normalized["conversions"] == purchases
    assert normalized["purchase_value"] == normalized["conversion_value"] == value


def test_missing_website_metrics_do_not_become_onsite_purchases():
    normalized = TikTokAdsConnector._normalise_row({"metrics": {
        "onsite_total_purchase": "99", "onsite_total_purchase_value_day29": "9999",
    }}, DAY)
    assert normalized["purchases"] is None
    assert normalized["purchase_value"] is None


def test_api_report_reads_website_purchases_without_writes():
    connector = TikTokAdsConnector({"advertiser_id": "1234567890"})
    def respond(request):
        assert request.method == "GET"
        assert request.url.path == "/open_api/v1.3/report/integrated/get/"
        assert "complete_payment" in json.loads(request.url.params["metrics"])
        return httpx.Response(200, json={"code": 0, "data": {"list": [{
            "dimensions": {"campaign_id": "42", "stat_time_day": DAY.isoformat()},
            "metrics": {"campaign_name": "Sales", "spend": "50", "clicks": "100",
                        "impressions": "1000", "complete_payment": "2",
                        "total_complete_payment_rate": "250"},
        }], "page_info": {"total_page": 1}}})
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        rows = connector._fetch_window(client, DAY, DAY)
    assert len(rows) == 1
    assert rows[0]["purchases"] == "2"
    assert rows[0]["purchase_value"] == "250"
    assert rows[0]["cost"] == "50"


@pytest.mark.parametrize("purchases,value", [("3", "180.50"), (0, 0), ("0", "0")])
def test_import_website_metrics_take_precedence_including_zero(db, purchases, value):
    import_tiktok_ads_rows(db, [{
        "campaign_id": "42", "campaign_name": "Sales", "complete_payment": purchases,
        "total_complete_payment_rate": value, "onsite_total_purchase": "99",
        "onsite_total_purchase_value_day29": "9999", "purchases": "88", "purchase_value": "8888",
    }], DAY)
    metric = db.scalars(select(CampaignDailyMetric).where(CampaignDailyMetric.source == "tiktok_ads")).one()
    assert metric.purchases == metric.conversions == Decimal(str(purchases))
    assert metric.purchase_value == metric.conversion_value == Decimal(str(value))


def test_resync_replaces_old_metrics_and_dashboard_recalculates_roas(db):
    import_tiktok_ads_rows(db, [{"campaign_id": "42", "campaign_name": "Sales", "cost": "100",
                                "purchases": "0", "purchase_value": "0"}], DAY)
    db.add(CampaignDailyMetric(source="meta_ads", metric_date=DAY, campaign_id="42", campaign_name="Other", cost=10))
    db.commit()
    normalized = TikTokAdsConnector._normalise_row({
        "dimensions": {"campaign_id": "42", "stat_time_day": DAY.isoformat()},
        "metrics": {"campaign_name": "Sales", "spend": "100", "complete_payment": "5",
                    "total_complete_payment_rate": "500", "clicks": "100", "impressions": "1000"},
    }, DAY)
    for _ in range(2):
        import_tiktok_ads_rows(db, [normalized], DAY)
    rows = db.scalars(select(CampaignDailyMetric).where(CampaignDailyMetric.source == "tiktok_ads")).all()
    assert len(rows) == 1
    assert rows[0].purchases == Decimal("5")
    assert db.scalars(select(CampaignDailyMetric).where(CampaignDailyMetric.source == "meta_ads")).one().cost == 10
    report = source_performance(db, "tiktok_ads", DAY, DAY)[0]
    assert report["conversions"] == report["purchases"] == 5
    assert report["conversion_value"] == report["purchase_value"] == 500
    assert report["cost"] == 100
    assert report["roas"] == 5


@pytest.mark.parametrize("count_header,value_header", [
    ("Purchases (website)", "Purchase value (website)"),
    ("complete_payment", "total_complete_payment_rate"),
])
def test_csv_import_recognizes_website_purchase_columns(db, count_header, value_header):
    text = f"Campaign name,Spend,{count_header},{value_header},onsite total purchase\nSales,50,2,250,99\n"
    assert import_tiktok_ads_csv(db, text, DAY) == 1
    report = source_performance(db, "tiktok_ads", DAY, DAY)[0]
    assert report["purchases"] == 2
    assert report["purchase_value"] == 250
    assert report["roas"] == 5
