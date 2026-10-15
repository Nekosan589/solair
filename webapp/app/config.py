import os

from dotenv import load_dotenv

# app/config.py
import os
from pathlib import Path

BASE_DIR: Path = Path(__file__).resolve().parent.parent  # solar-irradiance-api/
load_dotenv()


class Settings:
    APP_NAME: str = os.getenv("APP_NAME", "SOLAIR")

    # Bind to 0.0.0.0 so other devices on the LAN can reach the app.
    # Change to 127.0.0.1 if you only want local access on this machine.
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", "8000"))

    MODEL_LOAD_PATH: str = os.getenv("MODEL_LOAD_PATH", str(BASE_DIR / "app"/ "static" / "ml_artifacts"))
    MODEL_FILENAME: str = os.getenv("MODEL_FILENAME", "anfis_solar_model.pkl")

    SCALER_X_PATH: str = os.getenv(
        "SCALER_X_PATH", str(BASE_DIR / "app" / "static" / "ml_artifacts" / "scaler_X.pkl")
    )
    SCALER_Y_PATH: str = os.getenv(
        "SCALER_Y_PATH", str(BASE_DIR / "app" / "static" / "ml_artifacts" / "scaler_y.pkl")
    )

    STATIC_DIR: str = os.getenv(
        "STATIC_DIR", str(BASE_DIR / "app" / "static")
    )

    INDEX_FILE: str = os.getenv(
        "INDEX_FILE", str(BASE_DIR / "app" / "static" / "index.html")
    )


    OPEN_METEO_URL: str = "https://api.open-meteo.com/v1/forecast"
    FRESHNESS_HOURS: int = int(os.getenv("FRESHNESS_HOURS", "3"))

    # Feature order the model + scaler_X were trained on. MUST match
    # training exactly — scaler.transform() relies on column position, not
    # names. Column names here match the training script's FEATURE_COLS
    # verbatim, so there's no separate name-mapping layer to keep in sync.
    FEATURE_COLUMNS: list[str] = [
        "hour_sin",
        "hour_cos",
        "doy_sin",
        "doy_cos",
        "RH2M",
        "T2M",
        "SZA",
        "CLOUD_AMT",
        "WS10M",
        "CLOUD_AMT_lag1",
        "CLOUD_AMT_roll3",
        "kt_lag1",
        "kt_lag2",
        "kt_lag3",
    ]

    # Persistence-feature config, mirroring the training script's LAG_HOURS
    # / ROLL_WINDOW_HOURS.
    LAG_HOURS: list[int] = [1, 2, 3]
    ROLL_WINDOW_HOURS: int = 3

    # How many hours of weather to fetch BEFORE a requested window, purely
    # to seed lag/rolling features so the first hours of the target window
    # aren't computed from padding/defaults. Must cover the deepest lag
    # (max(LAG_HOURS)) plus the rolling window, with a little headroom.
    # Nighttime hours bootstrap kt=0 deterministically (see
    # services/prediction.py), so this doesn't need to reach all the way
    # back to genuine prior daylight — just past the previous sunset.
    FEATURE_BUFFER_HOURS: int = 6

    # Training excluded rows with SZA >= this cutoff (deep twilight/night)
    # from the *target* set — i.e. the model never learned to predict for
    # them. At inference, these hours are assigned kt=0 directly instead of
    # being passed through the model (see services/prediction.py).
    SZA_CUTOFF: float = 85.0
    
    DATABASE_FILE: str = "database.db"
    DATABASE_URL: str = os.getenv("DATABASE_URL", f"sqlite:///{DATABASE_FILE}")

settings = Settings()