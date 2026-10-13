"""
Ties together weather fetching, model prediction, and DB caching.

"Day" here means a PH-local (Asia/Manila) calendar day, converted to its
equivalent UTC window — see app/utils/dates.py. All storage and freshness
checks key off that UTC window, since IrradianceReading.hour is stored as
UTC (matching the model's UTC-trained features).

The model's kt_lag1/2/3 features are autoregressive (see
services/prediction.py), so _refresh fetches settings.FEATURE_BUFFER_HOURS
of extra hours before the target window purely to seed that lag chain,
then trims the result back down to the requested window before caching —
the buffer hours themselves are never stored or returned.

Freshness rule: a cached window's predictions are considered valid if they
were computed within the last FRESHNESS_HOURS (config.py). Once stale, the
row set for that (latitude, longitude, window) is replaced — not
accumulated — so the table only ever holds the latest prediction per hour.
"""
from datetime import date, datetime, timedelta

from sqlmodel import Session, delete, select

from app.config import settings
from app.enums import ForecastDay
from app.ml.artifacts import get_model, get_scaler_x, get_scaler_y
from app.models.irradiance import IrradianceReading
from app.services.prediction import predict_hourly_irradiance
from app.services.weather import get_hourly_weather
from app.utils.dates import get_ph_target_date, ph_day_utc_window


def _is_fresh(
    session: Session,
    latitude: float,
    longitude: float,
    window_start: datetime,
    window_end: datetime,
) -> bool:
    statement = (
        select(IrradianceReading)
        .where(
            IrradianceReading.latitude == latitude,
            IrradianceReading.longitude == longitude,
            IrradianceReading.hour >= window_start,
            IrradianceReading.hour < window_end,
        )
        .order_by(IrradianceReading.computed_at.desc())
    )
    latest = session.exec(statement).first()

    if latest is None:
        return False

    age = datetime.now() - latest.computed_at
    return age < timedelta(hours=settings.FRESHNESS_HOURS)


def _refresh(
    session: Session,
    latitude: float,
    longitude: float,
    window_start: datetime,
    window_end: datetime,
) -> list[IrradianceReading]:
    # Fetch extra hours BEFORE the target window so kt_lag1/2/3 and the
    # cloud lag/rolling features have real prior-hour data to seed from,
    # instead of starting the autoregressive chain cold at window_start.
    # Only the start is extended — lag/rolling features look backward
    # only, so there's nothing to gain by extending window_end.
    buffered_start = window_start - timedelta(hours=settings.FEATURE_BUFFER_HOURS)

    weather_df = get_hourly_weather(
        latitude=latitude,
        longitude=longitude,
        start_utc=buffered_start,
        end_utc=window_end,
    )

    # Predicts across the full buffered range — the sequential kt_lag
    # chain needs those extra hours even though we discard them next.
    predicted_df = predict_hourly_irradiance(
        weather_df=weather_df,
        model=get_model(),
        scaler_x=get_scaler_x(),
        scaler_y=get_scaler_y(),
        feature_columns=settings.FEATURE_COLUMNS,
    )

    # Trim back down to the actual requested window before caching/
    # returning — the buffer hours were only ever for seeding lags.
    result_df = predicted_df[
        (predicted_df["hour"] >= window_start) & (predicted_df["hour"] < window_end)
    ].reset_index(drop=True)

    # Clear stale rows for this location/window, then insert the fresh set.
    session.exec(
        delete(IrradianceReading).where(
            IrradianceReading.latitude == latitude, # type: ignore
            IrradianceReading.longitude == longitude, # type: ignore
            IrradianceReading.hour >= window_start, # type: ignore
            IrradianceReading.hour < window_end, # type: ignore
        )
    )

    now = datetime.now()
    rows = [
        IrradianceReading(
            latitude=latitude,
            longitude=longitude,
            hour=row["hour"].to_pydatetime().replace(tzinfo=None),
            predicted_irradiance=float(row["predicted_irradiance"]),
            computed_at=now,
        )
        for _, row in result_df.iterrows()
    ]
    session.add_all(rows)
    session.commit()
    for row in rows:
        session.refresh(row)

    return rows


def get_irradiance(
    session: Session, latitude: float, longitude: float, day: ForecastDay
) -> list[IrradianceReading]:
    """
    Returns cached predictions if fresh, otherwise recomputes and upserts
    before returning. 'day' resolves to a PH-local calendar date, converted
    to its UTC window internally.
    """
    target_date: date = get_ph_target_date(day)
    window_start, window_end = ph_day_utc_window(target_date)

    if _is_fresh(session, latitude, longitude, window_start, window_end):
        statement = (
            select(IrradianceReading)
            .where(
                IrradianceReading.latitude == latitude,
                IrradianceReading.longitude == longitude,
                IrradianceReading.hour >= window_start,
                IrradianceReading.hour < window_end,
            )
            .order_by(IrradianceReading.hour) # type: ignore
        )
        return list(session.exec(statement).all())

    return _refresh(session, latitude, longitude, window_start, window_end)
