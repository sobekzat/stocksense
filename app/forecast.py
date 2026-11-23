"""Прогноз спроса по SKU: глобальная модель градиентного бустинга (direct multi-horizon).

Одна модель обучается сразу на всех товарах: это даёт хорошее качество даже для SKU
с короткой историей (они "учатся" у похожих). Для каждого момента прогноза t и горизонта
h = 1..H строится пример: признаки известны на дату t, цель — продажи в день t+h.
Качество проверяется честным бэктестом на последних H днях и сравнивается с наивными бейзлайнами.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

HORIZON = 28
FEATURES = ["h", "dow", "month", "dom", "event", "r7", "r28", "r91", "dow_ratio", "trend", "zero_share",
            "price_rel", "sku_code"]


def retail_event(d: pd.Timestamp) -> int:
    """Календарь распродаж, известный заранее: 11.11, Black Friday, Новый год, 8 Марта, 14 Февраля."""
    m, day = d.month, d.day
    if m == 11 and 8 <= day <= 12:
        return 1
    if m == 11 and d.dayofweek == 4 and 23 <= day <= 29:  # Black Friday
        return 2
    if (m == 12 and day >= 18) or (m == 3 and day <= 7) or (m == 2 and 10 <= day <= 14):
        return 3
    return 0


def to_daily(sales: pd.DataFrame) -> pd.DataFrame:
    """Приводит продажи к ежедневной сетке (пропущенные дни = 0 продаж)."""
    s = sales.copy()
    s["date"] = pd.to_datetime(s["date"])
    g = s.groupby(["sku", "date"]).agg(qty=("qty", "sum"), price=("price", "mean")).reset_index()
    full = []
    end = g["date"].max()
    for sku, d in g.groupby("sku"):
        idx = pd.date_range(d["date"].min(), end, freq="D")
        d = d.set_index("date").reindex(idx)
        d["sku"] = sku
        d["qty"] = d["qty"].fillna(0.0)
        d["price"] = d["price"].ffill().bfill()
        full.append(d.rename_axis("date").reset_index())
    return pd.concat(full, ignore_index=True)


def _origin_features(q: np.ndarray, p: np.ndarray, t: int, dates: pd.DatetimeIndex) -> dict:
    """Признаки, известные на конец дня t (индекс включительно)."""
    hist = q[: t + 1]
    r7 = hist[-7:].mean()
    r28 = hist[-28:].mean()
    r91 = hist[-91:].mean()
    last56 = hist[-56:]
    dows = dates[: t + 1][-56:].dayofweek
    base = last56.mean() or 1e-6
    dow_mean = {d: (last56[dows == d].mean() if (dows == d).any() else base) for d in range(7)}
    price_rel = p[t] / (np.mean(p[max(0, t - 90): t + 1]) or 1.0)
    return {"r7": r7, "r28": r28, "r91": r91, "trend": (r28 + 1) / (r91 + 1),
            "zero_share": float((hist[-28:] == 0).mean()), "price_rel": price_rel,
            "_dow_mean": dow_mean, "_base": base}


def _rows_for_origin(of: dict, origin_date: pd.Timestamp, sku_code: int, horizon: int):
    for h in range(1, horizon + 1):
        d = origin_date + pd.Timedelta(days=h)
        yield {"h": h, "dow": d.dayofweek, "month": d.month, "dom": d.day, "event": retail_event(d),
               "r7": of["r7"], "r28": of["r28"], "r91": of["r91"],
               "dow_ratio": of["_dow_mean"][d.dayofweek] / of["_base"] if of["_base"] > 1e-6 else 1.0,
               "trend": of["trend"], "zero_share": of["zero_share"], "price_rel": of["price_rel"],
               "sku_code": sku_code, "_date": d}


def build_training(daily: pd.DataFrame, cutoff: pd.Timestamp, horizon: int = HORIZON,
                   step: int = 3) -> pd.DataFrame:
    rows = []
    codes = {s: i for i, s in enumerate(sorted(daily["sku"].unique()))}
    for sku, d in daily.groupby("sku"):
        d = d[d["date"] <= cutoff].reset_index(drop=True)
        q, p = d["qty"].to_numpy(float), d["price"].to_numpy(float)
        dates = pd.DatetimeIndex(d["date"])
        for t in range(56, len(d) - horizon, step):
            of = _origin_features(q, p, t, dates)
            for r in _rows_for_origin(of, dates[t], codes[sku], horizon):
                r["y"] = q[t + r["h"]]
                rows.append(r)
    return pd.DataFrame(rows)


def fit(train: pd.DataFrame) -> HistGradientBoostingRegressor:
    model = HistGradientBoostingRegressor(loss="poisson", max_iter=300, learning_rate=0.05,
                                          max_leaf_nodes=31, min_samples_leaf=40,
                                          categorical_features=[FEATURES.index("sku_code")],
                                          random_state=42)
    model.fit(train[FEATURES], train["y"])
    return model


def predict(model, daily: pd.DataFrame, origin: pd.Timestamp, horizon: int = HORIZON) -> pd.DataFrame:
    codes = {s: i for i, s in enumerate(sorted(daily["sku"].unique()))}
    rows = []
    for sku, d in daily.groupby("sku"):
        d = d[d["date"] <= origin].reset_index(drop=True)
        if len(d) < 14:
            continue
        q, p = d["qty"].to_numpy(float), d["price"].to_numpy(float)
        of = _origin_features(q, p, len(d) - 1, pd.DatetimeIndex(d["date"]))
        for r in _rows_for_origin(of, d["date"].iloc[-1], codes[sku], horizon):
            r["sku"] = sku
            rows.append(r)
    X = pd.DataFrame(rows)
    X["forecast"] = np.clip(model.predict(X[FEATURES]), 0, None)
    return X.rename(columns={"_date": "date"})[["sku", "date", "h", "forecast"]]


def wape(y: np.ndarray, yhat: np.ndarray) -> float:
    return float(np.abs(y - yhat).sum() / max(np.abs(y).sum(), 1e-9))


def backtest(daily: pd.DataFrame, horizon: int = HORIZON) -> dict:
    """Обучаем на данных до (конец − H), прогнозируем последние H дней, сравниваем с бейзлайнами."""
    end = daily["date"].max()
    cutoff = end - pd.Timedelta(days=horizon)
    model = fit(build_training(daily, cutoff, horizon))
    fc = predict(model, daily, cutoff, horizon)
    actual = daily[daily["date"] > cutoff][["sku", "date", "qty"]]
    m = fc.merge(actual, on=["sku", "date"], how="inner")
    hist = daily[daily["date"] <= cutoff]
    r28 = hist.groupby("sku")["qty"].apply(lambda s: s.tail(28).mean())
    m["naive"] = m["sku"].map(r28)
    last7 = hist[hist["date"] > cutoff - pd.Timedelta(days=7)]
    lw = {(r.sku, r.date.dayofweek): r.qty for r in last7.itertuples()}
    m["snaive"] = [lw.get((s, d.dayofweek), 0.0) for s, d in zip(m["sku"], m["date"])]
    res = {"model": wape(m["qty"].values, m["forecast"].values),
           "naive_mean28": wape(m["qty"].values, m["naive"].values),
           "seasonal_naive": wape(m["qty"].values, m["snaive"].values)}
    res["improvement_vs_naive"] = 1 - res["model"] / res["naive_mean28"]
    res["cutoff"] = cutoff.date().isoformat()
    return {k: (round(v, 4) if isinstance(v, float) else v) for k, v in res.items()}


def forecast_future(daily: pd.DataFrame, horizon: int = HORIZON) -> pd.DataFrame:
    end = daily["date"].max()
    model = fit(build_training(daily, end, horizon))
    return predict(model, daily, end, horizon)
