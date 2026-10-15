"""
Runs the ANFIS model over weather data to produce hourly solar irradiance
predictions.

IMPORTANT — this model predicts kt (clear-sky index = GHI / GHI_clearsky),
not raw GHI directly (see the training script's section 3). Real GHI is
reconstructed afterwards as kt_pred * GHI_clearsky.

IMPORTANT — kt_lag1/2/3 are AUTOREGRESSIVE: they need the actual kt value
from 1/2/3 hours before. At inference time there's no "actual" kt for
hours that haven't happened yet — only forecast weather — so predictions
must be made SEQUENTIALLY, hour by hour, feeding each hour's predicted kt
forward into the next hours' lag features. This is why this function loops
row-by-row instead of scoring the whole DataFrame in one batch call, unlike
a typical scikit-learn-style model.

Nighttime hours (SZA >= SZA_CUTOFF) are assigned kt = 0 directly rather
than passed through the model — this matches the training script, which
excluded those rows from the target set entirely (the model never learned
to predict for them), and is physically well-justified (GHI ~ 0 at night
regardless of weather).
"""
import numpy as np
import pandas as pd

from webapp.app.config import settings


def predict_hourly_irradiance(
    weather_df: pd.DataFrame,
    model,
    scaler_x,
    scaler_y,
    feature_columns: list[str],
    sza_cutoff: float | None = None,
) -> pd.DataFrame:
    """
    Returns weather_df (sorted by hour) with two added columns:
      - 'kt': predicted clear-sky index for each hour (0 for night hours)
      - 'predicted_irradiance': reconstructed GHI in W/m^2
        (= kt * GHI_clearsky, clipped to >= 0)

    feature_columns order MUST match what scaler_x/model were trained on.
    Any column named 'kt_lag{N}' is resolved from this function's own
    running predictions (N hours back in the sorted sequence); every other
    column is read directly from weather_df for that row.

    weather_df must already contain GHI_clearsky and SZA (see
    services/weather.py) and every non-kt_lag feature column.
    """
    if sza_cutoff is None:
        sza_cutoff = settings.SZA_CUTOFF

    non_kt_lag_cols = [c for c in feature_columns if not c.startswith("kt_lag")]
    missing = [c for c in non_kt_lag_cols if c not in weather_df.columns]
    if missing:
        raise ValueError(f"weather_df is missing required feature columns: {missing}")
    if "GHI_clearsky" not in weather_df.columns:
        raise ValueError("weather_df is missing 'GHI_clearsky' — required to reconstruct GHI from kt")
    if "SZA" not in weather_df.columns:
        raise ValueError("weather_df is missing 'SZA' — required for the night-hour cutoff")

    df = weather_df.sort_values("hour").reset_index(drop=True)
    n = len(df)

    kt_values = np.zeros(n, dtype=np.float64)
    ghi_values = np.zeros(n, dtype=np.float64)

    for i in range(n):
        sza = df.loc[i, "SZA"]

        if sza >= sza_cutoff:
            # Night / deep twilight — outside training distribution for
            # the model's target set; GHI is physically ~0 regardless of
            # weather, so skip the model entirely.
            kt = 0.0
        else:
            row_values = []
            for col in feature_columns:
                if col.startswith("kt_lag"):
                    lag = int(col[len("kt_lag"):])
                    src_idx = i - lag
                    # Falls back to 0 only if the lag would reach before
                    # the fetched range even after FEATURE_BUFFER_HOURS —
                    # shouldn't normally happen; 0 mirrors the night-hour
                    # convention if it does.
                    row_values.append(kt_values[src_idx] if src_idx >= 0 else 0.0)
                else:
                    row_values.append(df.loc[i, col])

            X = np.array(row_values, dtype=np.float64).reshape(1, -1)
            X_scaled = scaler_x.transform(X).astype(np.float32)

            kt_scaled_pred = model.predict(X_scaled)
            kt_pred = scaler_y.inverse_transform(
                np.asarray(kt_scaled_pred).reshape(-1, 1)
            ).ravel()[0]
            kt = float(np.clip(kt_pred, 0, 1.5))  # matches training's clip range

        kt_values[i] = kt
        clearsky = df.loc[i, "GHI_clearsky"]
        ghi_values[i] = max(0.0, kt * clearsky)

    result_df = df.copy()
    result_df["kt"] = kt_values
    result_df["predicted_irradiance"] = ghi_values
    return result_df
