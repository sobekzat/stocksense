"""Демо-данные интернет-магазина: 24 SKU, 26 месяцев продаж + остатки на складе."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

PRODUCTS = [
    ("PHONE-CASE-IP15", 3990, 9.0), ("USB-C-CABLE-1M", 1990, 14.0), ("AIRPODS-CASE", 2490, 6.0),
    ("POWERBANK-10K", 8990, 4.0), ("SCREEN-GLASS-S24", 1490, 11.0), ("SMARTWATCH-BAND", 2990, 5.0),
    ("WIRELESS-CHARGER", 6990, 2.5), ("BT-SPEAKER-MINI", 12990, 1.4), ("CAR-HOLDER", 3490, 3.2),
    ("LAPTOP-STAND", 9990, 1.1), ("MOUSE-WIRELESS", 5990, 2.2), ("KEYBOARD-MECH", 24990, 0.6),
    ("WEBCAM-1080P", 14990, 0.5), ("RING-LIGHT-26", 7990, 1.0), ("HDMI-CABLE-2M", 2490, 2.8),
    ("SD-CARD-128GB", 5490, 2.0), ("GAMEPAD-PC", 11990, 0.7), ("HEADSET-GAMING", 18990, 0.45),
    ("SELFIE-STICK", 3990, 0.9), ("PHONE-CASE-A55", 2990, 4.5), ("TRIPOD-MINI", 4490, 0.6),
    ("ROUTER-WIFI6", 29990, 0.25), ("THERMOS-500ML", 6490, 1.2), ("HUMIDIFIER", 15990, 0.8),
]


def generate(seed: int = 42, end: str = "2026-11-22", days: int = 790):
    rng = np.random.default_rng(seed)
    dates = pd.date_range(end=end, periods=days, freq="D")
    rows, stock = [], []
    dow_effect = np.array([0.95, 0.9, 0.95, 1.0, 1.1, 1.25, 0.85])
    for i, (sku, price, base) in enumerate(PRODUCTS):
        trend = np.linspace(1.0, rng.uniform(0.7, 1.6), days)
        season = np.ones(days)
        doy = dates.dayofyear.to_numpy()
        if sku in ("HUMIDIFIER", "THERMOS-500ML"):  # зимние товары
            season = 1 + 0.9 * np.cos((doy - 15) / 365 * 2 * np.pi)
        promo = np.where((dates.month == 11) & (dates.day >= 8) & (dates.day <= 12), 2.2, 1.0)  # 11.11
        lam = base * trend * season * dow_effect[dates.dayofweek] * promo
        qty = rng.poisson(np.clip(lam, 0.01, None))
        p = np.where(promo > 1, price * 0.85, price)
        for d, q, pp in zip(dates, qty, p):
            if q > 0:
                rows.append({"date": d.date().isoformat(), "sku": sku, "qty": int(q), "price": float(pp)})
        recent = qty[-28:].mean()
        cover = rng.choice([3, 8, 15, 30, 45, 120], p=[0.15, 0.2, 0.2, 0.25, 0.1, 0.1])
        stock.append({"sku": sku, "stock": int(recent * cover), "lead_time_days": int(rng.choice([5, 7, 10, 14, 21])),
                      "unit_cost": round(price * rng.uniform(0.45, 0.65), 0)})
    return pd.DataFrame(rows), pd.DataFrame(stock)


def write_demo(folder: Path) -> tuple[Path, Path]:
    folder.mkdir(parents=True, exist_ok=True)
    sales, stock = generate()
    a, b = folder / "demo_sales.csv", folder / "demo_stock.csv"
    sales.to_csv(a, index=False)
    stock.to_csv(b, index=False)
    return a, b


if __name__ == "__main__":
    print(write_demo(Path(__file__).parent))
