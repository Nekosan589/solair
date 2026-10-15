from enum import Enum

class PriorityClass(Enum):
    HIGH_PRIORITY = 'high_priority'
    LOW_PRIORITY = 'low_priority'

class DateFilter(Enum):
    TODAY = 'today'
    THIS_WEEK = 'this_week'
    THIS_MONTH = 'this_month'

class ForecastDay(str, Enum):
    today = "today"
    tomorrow = "tomorrow"

