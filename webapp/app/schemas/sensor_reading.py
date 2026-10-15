from typing import Optional

from sqlmodel import SQLModel, Field as SQLField
from webapp.app.enums import DateFilter
from datetime import datetime

class SensorReadingBase(SQLModel):
    date_applicable: datetime = SQLField(default=datetime.today, index=True)
    solar_consumption: float
    grid_consumption: float
    high_priority_consumption: float
    low_priority_consumption: float

class SensorReadingCreate(SensorReadingBase):
    pass

class SensorReadingRead(SensorReadingBase):
    id: int

class SensorReadingUpdate(SensorReadingBase):
    date_applicable: datetime = SQLField(default=datetime.today, index=True)
    solar_consumption: Optional[float] = None
    grid_consumption: Optional[float] = None
    high_priority_consumption: Optional[float] = None
    low_priority_consumption: Optional[float] = None    

class ConsumptionSummary(SQLModel):
    time_frame: DateFilter
    high_priority_consumption: float
    low_priority_consumption: float
    solar_consumption: float
    grid_consumption: float