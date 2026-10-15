from webapp.app.schemas.sensor_reading import SensorReadingBase
from sqlmodel import Field as SQLField

class SensorReading(SensorReadingBase, table=True):
    id: int | None = SQLField(default=None, primary_key=True)