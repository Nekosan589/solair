from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel, UniqueConstraint


class IrradianceReading(SQLModel, table=True):
    """
    Stores one predicted irradiance value per (location, hour). Upserted by
    the service layer whenever the cached values go stale — see
    app/services/irradiance_service.py.
    """

    __table_args__ = (
        UniqueConstraint("latitude", "longitude", "hour", name="uq_lat_lon_hour"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    latitude: float = Field(index=True)
    longitude: float = Field(index=True)
    hour: datetime = Field(index=True)  # forecast hour this value applies to
    predicted_irradiance: float
    computed_at: datetime = Field(default_factory=datetime.now)  # when the model was run
