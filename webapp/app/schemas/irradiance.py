from sqlmodel import SQLModel


class HourlyIrradiance(SQLModel):
    """Single hour's predicted irradiance value, as returned by the API."""
    hour: str
    predicted_irradiance: float

class IrradianceForecast(SQLModel):
    """Full response payload for a day's forecast at a given location."""
    latitude: float
    longitude: float
    day: str
    readings: list[HourlyIrradiance]
