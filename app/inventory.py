"""Управление запасами на основе прогноза: точка заказа, страховой запас, ABC-анализ."""
from __future__ import annotations

from statistics import NormalDist

import numpy as np
import pandas as pd


def abc_classes(revenue: pd.Series) -> pd.Series:
    """A — товары, дающие первые 80% выручки, B — следующие 15%, C — остальные 5%."""
    r = revenue.sort_values(ascending=False)
    share = r.cumsum() / max(r.sum(), 1e-9)
    cls = np.where(share <= 0.8, "A", np.where(share <= 0.95, "B", "C"))
    cls[0] = "A"
    return pd.Series(cls, index=r.index)


def plan(daily: pd.DataFrame, forecast: pd.DataFrame, stock: pd.DataFrame,
         service_level: float = 0.95, review_days: int = 14) -> pd.DataFrame:
    """stock: sku, stock, lead_time_days, unit_cost.

    Страховой запас = z · σ_дневной_ошибки · √(срок поставки).
    Точка заказа = спрос за срок поставки (по прогнозу) + страховой запас.
    Заказ = спрос за (срок поставки + период пересмотра) + страховой запас − остаток.
    """
    z = NormalDist().inv_cdf(service_level)
    last90 = daily[daily["date"] > daily["date"].max() - pd.Timedelta(days=90)]
    revenue = (last90["qty"] * last90["price"]).groupby(last90["sku"]).sum()
    abc = abc_classes(revenue)
    sigma = last90.groupby("sku")["qty"].std().fillna(0)
    price = daily.sort_values("date").groupby("sku")["price"].last()
    out = []
    for sku, f in forecast.groupby("sku"):
        f = f.sort_values("h")
        st = stock[stock["sku"] == sku]
        on_hand = float(st["stock"].iloc[0]) if len(st) else 0.0
        lead = int(st["lead_time_days"].iloc[0]) if len(st) else 7
        cost = float(st["unit_cost"].iloc[0]) if len(st) else float("nan")
        if np.isnan(cost):
            cost = float(price.get(sku, 0)) * 0.6  # себестоимость неизвестна — оценка 60% от цены
        daily_fc = f["forecast"].to_numpy()
        avg = float(daily_fc.mean())
        lead_demand = float(daily_fc[:lead].sum()) if lead <= len(daily_fc) else avg * lead
        cover_demand = avg * (lead + review_days)
        safety = z * float(sigma.get(sku, 0)) * np.sqrt(lead)
        rop = lead_demand + safety
        cum = np.cumsum(daily_fc)
        stockout_day = int(np.argmax(cum > on_hand)) + 1 if (cum > on_hand).any() else None
        days_cover = on_hand / avg if avg > 0 else float("inf")
        order = max(0.0, cover_demand + safety - on_hand)
        if on_hand <= rop:
            status = "order_now"
        elif days_cover <= lead + 7:
            status = "order_soon"
        elif days_cover > 90:
            status = "overstock"
        else:
            status = "ok"
        if status in ("ok", "overstock"):
            order = 0.0  # заказ не нужен до следующего пересмотра
        unit_price = float(price.get(sku, 0))
        lost = 0.0
        if stockout_day is not None and stockout_day <= lead:
            # продажи, которые сгорят, пока едет заказ, сделанный сегодня
            lost = float(daily_fc[stockout_day - 1:lead].sum()) * unit_price
        out.append({
            "sku": sku, "abc": abc.get(sku, "C"), "status": status, "stock": on_hand,
            "lead_time_days": lead, "forecast_28d": round(float(daily_fc.sum()), 1),
            "avg_daily": round(avg, 2), "days_of_cover": None if np.isinf(days_cover) else round(days_cover, 1),
            "stockout_in_days": stockout_day, "safety_stock": round(safety, 1),
            "reorder_point": round(rop, 1), "order_qty": int(np.ceil(order)),
            "order_cost": round(np.ceil(order) * cost, 0),
            "frozen_capital": round(max(0.0, on_hand - avg * 90) * cost, 0) if status == "overstock" else 0.0,
            "revenue_at_risk": round(lost, 0), "price": unit_price,
        })
    order = {"order_now": 0, "order_soon": 1, "overstock": 2, "ok": 3}
    return pd.DataFrame(out).sort_values(["status", "abc"], key=lambda s: s.map(order) if s.name == "status" else s)
