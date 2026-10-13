"""
Fetches hourly weather parameters from Open-Meteo and augments them with
everything the model needs EXCEPT the kt_lag* features — those are
autoregressive (they depend on the model's own predictions) and are
computed in services/prediction.py instead.

What this module computes, matching the training script exactly:
- hour_sin/cos, doy_sin/cos          — cyclical time features
- RH2M, T2M, CLOUD_AMT, WS10M        — renamed straight from Open-Meteo
- SZA                                — solar zenith angle via pvlib
- GHI_clearsky                       — Haurwitz clear-sky model (pvlib),
                                        needs only SZA; used to reconstruct
                                        real GHI from predicted kt
- CLOUD_AMT_lag1, CLOUD_AMT_roll3    — deterministic from forecast cloud
                                        cover, no model dependency

Notes:
- Wind speed at 2 m isn't available from Open-Meteo (only 10/80/120/180 m).
  The training script now uses WS10M directly, which matches Open-Meteo's
  native wind_speed_10m — no mismatch to work around anymore.
- day_of_year cycle uses 365 (not 365.25) to match the training script's
  `np.sin(2 * np.pi * df["DOY"] / 365)` exactly.
"""
from datetime import datetime

import numpy as np
import pandas as pd
import pvlib.clearsky
import requests
from pvlib.solarposition import get_solarposition

from app.config import settings


def _add_cyclical_time_features(df: pd.DataFrame) -> pd.DataFrame:
    hour = df["hour"].dt.hour
    day_of_year = df["hour"].dt.dayofyear

    df["hour_sin"] = np.sin(2 * np.pi * hour / 24)
    df["hour_cos"] = np.cos(2 * np.pi * hour / 24)
    df["doy_sin"] = np.sin(2 * np.pi * day_of_year / 365)
    df["doy_cos"] = np.cos(2 * np.pi * day_of_year / 365)
    return df


def get_hourly_weather(
    latitude: float,
    longitude: float,
    start_utc: datetime,
    end_utc: datetime,
) -> pd.DataFrame:
    """
    Returns a DataFrame with one row per hour in the half-open UTC window
    [start_utc, end_utc), with every feature column EXCEPT kt_lag1/2/3.

    start_utc/end_utc are naive datetimes whose values represent UTC. The
    window may span two UTC calendar dates. Callers are responsible for
    passing a window extended by settings.FEATURE_BUFFER_HOURS at the
    start if they need clean lag/rolling values for the first hours of
    their actual target range (see services/irradiance_service.py).
    """
    from datetime import timedelta

    open_meteo_start_date = start_utc.date().isoformat()
    open_meteo_end_date = (end_utc - timedelta(seconds=1)).date().isoformat()

    params = {
        "latitude": latitude,
        "longitude": longitude,
        "start_date": open_meteo_start_date,
        "end_date": open_meteo_end_date,
        "timezone": "UTC",
        "hourly": ",".join(
            [
                "relative_humidity_2m",
                "temperature_2m",
                "cloud_cover",
                "wind_speed_10m",
            ]
        ),
    }

    response = requests.get(settings.OPEN_METEO_URL, params=params, timeout=15)
    response.raise_for_status()
    data = response.json()

    hourly = data["hourly"]
    df = pd.DataFrame(
        {
            "hour": pd.to_datetime(hourly["time"], utc=True).tz_localize(None),
            "RH2M": hourly["relative_humidity_2m"],
            "T2M": hourly["temperature_2m"],
            "CLOUD_AMT": hourly["cloud_cover"],
            "WS10M": hourly["wind_speed_10m"],
        }
    )

    df = df[(df["hour"] >= start_utc) & (df["hour"] < end_utc)].reset_index(drop=True)

    solar_pos = get_solarposition(time=df["hour"], latitude=latitude, longitude=longitude)
    df["SZA"] = solar_pos["zenith"].to_numpy()

    # Clear-sky GHI via the Haurwitz model — needs only zenith angle,
    # matching how the training script derives GHI_clearsky. Clipped to
    # avoid divide-by-~0 when reconstructing kt * GHI_clearsky near the
    # horizon, same as training.
    clearsky_ghi = pvlib.clearsky.haurwitz(df["SZA"])["ghi"]
    df["GHI_clearsky"] = clearsky_ghi.clip(lower=1.0)

    df = _add_cyclical_time_features(df)

    # Deterministic persistence features — safe to compute from forecast
    # cloud cover directly, unlike kt_lag* which need the model's own
    # predictions (see services/prediction.py).
    df["CLOUD_AMT_lag1"] = df["CLOUD_AMT"].shift(1)
    # First row of the fetched range has no prior hour to shift from — fall
    # back to "assume unchanged" rather than leaving NaN (which would
    # silently poison scaler_x.transform()). In practice this only affects
    # the very first buffer row, which gets trimmed away before it reaches
    # the target window (see irradiance_service.py).
    df["CLOUD_AMT_lag1"] = df["CLOUD_AMT_lag1"].fillna(df["CLOUD_AMT"])
    df["CLOUD_AMT_roll3"] = (
        df["CLOUD_AMT"].rolling(settings.ROLL_WINDOW_HOURS, min_periods=1).mean()
    )

    return df
