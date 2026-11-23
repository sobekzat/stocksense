import numpy as np
import pandas as pd
from fastapi.testclient import TestClient

from app.forecast import backtest, retail_event, to_daily
from app.inventory import abc_classes, plan
from app.main import app
from sample.generate import generate

client = TestClient(app)


def test_to_daily_fills_gaps():
    s = pd.DataFrame({"date": ["2026-01-01", "2026-01-04"], "sku": ["A", "A"], "qty": [2, 3], "price": [10, 10]})
    d = to_daily(s)
    assert len(d) == 4 and d["qty"].tolist() == [2, 0, 0, 3]


def test_retail_calendar():
    assert retail_event(pd.Timestamp("2026-11-11")) == 1
    assert retail_event(pd.Timestamp("2026-11-27")) == 2  # Black Friday 2026
    assert retail_event(pd.Timestamp("2026-06-15")) == 0


def test_abc():
    cls = abc_classes(pd.Series({"a": 800, "b": 150, "c": 50}))
    assert cls.to_dict() == {"a": "A", "b": "B", "c": "C"}


def test_model_beats_naive_baseline():
    sales, _ = generate()
    m = backtest(to_daily(sales))
    assert m["model"] < m["naive_mean28"] and m["model"] < m["seasonal_naive"]
    assert m["improvement_vs_naive"] > 0.1


def test_plan_logic():
    dates = pd.date_range("2026-01-01", periods=60)
    daily = pd.DataFrame({"sku": "X", "date": dates, "qty": 10.0, "price": 100.0})
    fc = pd.DataFrame({"sku": "X", "h": range(1, 29), "forecast": 10.0})
    low = plan(daily, fc, pd.DataFrame({"sku": ["X"], "stock": [30], "lead_time_days": [7], "unit_cost": [50]}))
    r = low.iloc[0]
    assert r["status"] == "order_now" and r["stockout_in_days"] == 4
    assert r["order_qty"] == 21 * 10 - 30  # (7 + 14 дней) * 10 − остаток; σ=0 → страховой запас 0
    assert r["revenue_at_risk"] == 4 * 10 * 100  # дни 4..7 без товара
    high = plan(daily, fc, pd.DataFrame({"sku": ["X"], "stock": [5000], "lead_time_days": [7], "unit_cost": [50]}))
    assert high.iloc[0]["status"] == "overstock" and high.iloc[0]["frozen_capital"] == (5000 - 900) * 50


def test_api_demo_and_po():
    r = client.get("/api/demo")
    assert r.status_code == 200
    j = r.json()
    assert j["summary"]["skus"] == 24 and set(j["series"]) == {i["sku"] for i in j["items"]}
    po = client.get("/api/purchase-order.csv")
    assert po.status_code == 200 and "order_qty" in po.text


def test_api_rejects_short_history():
    csv = "date,sku,qty\n2026-01-01,A,1\n2026-01-02,A,2\n"
    r = client.post("/api/forecast", files={"sales": ("s.csv", csv, "text/csv")})
    assert r.status_code == 422
