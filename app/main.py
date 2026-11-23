"""StockSense — API: продажи (+ остатки) → прогноз спроса и план закупок."""
from __future__ import annotations

import io
from pathlib import Path

import numpy as np
import pandas as pd
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .forecast import backtest, forecast_future, to_daily
from .inventory import plan

BASE = Path(__file__).resolve().parent.parent
app = FastAPI(title="StockSense", version="1.0.0",
              description="Прогноз спроса и план закупок для интернет-магазинов")
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")


def _read_csv(data: bytes, required: set[str], name: str) -> pd.DataFrame:
    try:
        df = pd.read_csv(io.BytesIO(data), sep=None, engine="python")
    except Exception as e:  # noqa: BLE001
        raise HTTPException(422, f"{name}: не удалось прочитать CSV ({e})")
    df.columns = [c.strip().lower() for c in df.columns]
    missing = required - set(df.columns)
    if missing:
        raise HTTPException(422, f"{name}: нет колонок {', '.join(sorted(missing))}")
    return df


def run(sales: pd.DataFrame, stock: pd.DataFrame) -> dict:
    sales["date"] = pd.to_datetime(sales["date"], dayfirst=False, errors="coerce")
    sales = sales.dropna(subset=["date", "sku", "qty"])
    if "price" not in sales:
        sales["price"] = 0.0
    daily = to_daily(sales)
    span = (daily["date"].max() - daily["date"].min()).days
    if span < 120:
        raise HTTPException(422, "Нужна история продаж минимум за 4 месяца")
    metrics = backtest(daily)
    fc = forecast_future(daily)
    p = plan(daily, fc, stock)
    hist = daily[daily["date"] > daily["date"].max() - pd.Timedelta(days=120)]
    series = {}
    for sku in p["sku"]:
        h = hist[hist["sku"] == sku]
        f = fc[fc["sku"] == sku]
        series[sku] = {"hist_dates": h["date"].dt.strftime("%Y-%m-%d").tolist(), "hist": h["qty"].tolist(),
                       "fc_dates": f["date"].dt.strftime("%Y-%m-%d").tolist(),
                       "fc": f["forecast"].round(2).tolist()}
    items = p.replace({np.nan: None}).to_dict(orient="records")
    return {
        "metrics": metrics,
        "summary": {
            "skus": len(p),
            "order_now": int((p["status"] == "order_now").sum()),
            "order_budget": float(p.loc[p["status"] == "order_now", "order_cost"].sum()),
            "revenue_at_risk": float(p["revenue_at_risk"].sum()),
            "frozen_capital": float(p["frozen_capital"].sum()),
        },
        "items": items,
        "series": series,
    }


@app.get("/")
def index():
    return FileResponse(BASE / "static" / "index.html")


@app.post("/api/forecast")
async def forecast_endpoint(sales: UploadFile = File(...), stock: UploadFile | None = File(None)):
    s = _read_csv(await sales.read(), {"date", "sku", "qty"}, "Продажи")
    st = (_read_csv(await stock.read(), {"sku", "stock"}, "Остатки") if stock is not None
          else pd.DataFrame(columns=["sku", "stock", "lead_time_days", "unit_cost"]))
    for col, default in (("lead_time_days", 7), ("unit_cost", np.nan)):
        if col not in st:
            st[col] = default
    st["unit_cost"] = st["unit_cost"].astype(float)
    return run(s, st)


@app.get("/api/demo")
def demo():
    a, b = BASE / "sample" / "demo_sales.csv", BASE / "sample" / "demo_stock.csv"
    if not a.exists():
        from sample.generate import write_demo  # type: ignore
        write_demo(BASE / "sample")
    return run(pd.read_csv(a), pd.read_csv(b))
