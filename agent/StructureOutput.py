from pydantic import BaseModel, Field
from typing import Literal

class CapitalInfo(BaseModel):
    name: str
    location: str
    vibe: str
    economy: str

class WeatherInfo(BaseModel):
    date: str = Field(description="date")
    location: str = Field(description="City name or coordinates")
    weather: str = Field(description="Weather details")
    temperature: float = Field(description="Temperature")
    units: Literal["celsius", "fahrenheit"] = Field(
        default="celsius",
        description="Temperature unit preference"
    )