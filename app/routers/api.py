from typing import List
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Query, HTTPException
from sqlmodel import select, func

from app.database import SessionDep
from app.enums import DateFilter, ForecastDay
from app.models.sensor_reading import SensorReading
from app.schemas.sensor_reading import SensorReadingRead, SensorReadingUpdate, SensorReadingCreate, ConsumptionSummary
from app.schemas.irradiance import IrradianceForecast, HourlyIrradiance
from app.services.irradiance_service import get_irradiance
from app.utils.dates import get_date_range

router = APIRouter(prefix="/api")

PH_TZ = ZoneInfo("Asia/Manila")

# --------- SENSOR READINGS -------------
@router.post("/sensor_readings/", response_model=SensorReadingRead)
def create_sensor_reading(sensor_reading: SensorReadingCreate, session: SessionDep):
    db_sensor_reading = SensorReading.model_validate(sensor_reading)
    session.add(db_sensor_reading)
    session.commit()
    session.refresh(db_sensor_reading)
    return db_sensor_reading

@router.get("/sensor_readings/", response_model=List[SensorReadingRead])
async def read_sensor_readings(
    session: SessionDep,
    offset: int = 0,
    limit: int = 100,
    ):
    db_sensor_readings = session.exec(select(SensorReading).offset(offset).limit(limit)).all()
    return db_sensor_readings

@router.get("/sensor_readings/{reading_id}", response_model=SensorReadingRead)
async def read_sensor_reading(reading_id: int, session: SessionDep):
    db_sensor_reading = session.get(SensorReading, reading_id)
    if not db_sensor_reading:
        raise HTTPException(status_code=404, detail="Sensor Reading not found")
    return db_sensor_reading

@router.patch("/sensor_readings/{reading_id}", response_model=SensorReadingRead)
def update_sensor_reading(reading_id: int, sensor_reading_update: SensorReadingUpdate, session: SessionDep):
    db_sensor_reading = session.get(SensorReadingUpdate, reading_id)
    if not db_sensor_reading:
        raise HTTPException(status_code=404, detail="Sensor Reading not found")
    sensor_reading_data = sensor_reading_update.model_dump(exclude_unset=True)
    db_sensor_reading.sqlmodel_update(sensor_reading_data)
    session.add(sensor_reading_data)
    session.commit()
    session.refresh(sensor_reading_data)
    return sensor_reading_data

@router.delete("/sensor_readings/{reading_id}", response_model=SensorReadingRead)
def delete_sensor_reading(reading_id: int, session: SessionDep):
    db_sensor_reading = session.get(SensorReading, reading_id)
    if not db_sensor_reading:
        raise HTTPException(status_code=404, detail="Sensor Reading not found")
    session.delete(db_sensor_reading)
    session.commit()
    return {"ok": True}

# --------- CONSUMPTION -------------
@router.get("/consumption/{time_frame}", response_model=ConsumptionSummary)
def get_consumption(time_frame: DateFilter, session: SessionDep):
    time_frame_start, time_frame_end = get_date_range(time_frame)
    query = select(
        func.sum(SensorReading.high_priority_consumption),
        func.sum(SensorReading.low_priority_consumption),
        func.sum(SensorReading.solar_consumption),
        func.sum(SensorReading.grid_consumption),
    ).where(
        SensorReading.date_applicable >= time_frame_start,
        SensorReading.date_applicable <= time_frame_end,
    )

    high, low, solar, grid = session.exec(query).one()

    return ConsumptionSummary(
        time_frame=time_frame,
        high_priority_consumption=high or 0.0,
        low_priority_consumption=low or 0.0,
        solar_consumption=solar or 0.0,
        grid_consumption=grid or 0.0,
    )

# --------- SOLAR IRRADIANCE -------------
@router.get("/{day}", response_model=IrradianceForecast)
def get_solar_irradiance(
    day: ForecastDay,
    session: SessionDep,
    latitude: float = Query(..., ge=-90, le=90),
    longitude: float = Query(..., ge=-180, le=180),
):
    """
    Returns predicted hourly solar irradiance for a location, either for
    'today' or 'tomorrow' in Philippine time (Asia/Manila). Backed by a
    cache — see app/services/irradiance_service.py for the freshness/
    refresh logic.

    'today'/'tomorrow' resolve to PH-local calendar days (see
    app/utils/dates.py), which are converted internally to their
    equivalent UTC window for fetching weather and computing model
    features — the model itself stays UTC-anchored throughout. Only the
    displayed 'hour' timestamps in the response are converted to PH time.
    """
    readings = get_irradiance(session, latitude, longitude, day)

    return IrradianceForecast(
        latitude=latitude,
        longitude=longitude,
        day=day.value,
        readings=[
            HourlyIrradiance(
                # r.hour is stored naive-but-UTC — localize it as UTC first,
                # then convert to PH local time for display.
                hour=r.hour.replace(tzinfo=ZoneInfo("UTC"))
                .astimezone(PH_TZ)
                .strftime("%Y-%m-%dT%H:%M"),
                predicted_irradiance=r.predicted_irradiance,
            )
            for r in readings
        ],
    )

