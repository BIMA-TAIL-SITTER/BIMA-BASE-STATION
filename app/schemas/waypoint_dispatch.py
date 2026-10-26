"""Versioned nearest-owner missions; independent of the legacy mission protocol."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class Waypoint(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    task_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    sequence: int = Field(ge=1, le=200)
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    alt_m: float = Field(gt=0, le=500)


class CompanionEndpoint(BaseModel):
    model_config = ConfigDict(extra="forbid")
    host: str = Field(min_length=1, max_length=253, pattern=r"^[a-zA-Z0-9.:-]+$")
    port: int = Field(ge=1, le=65535)


class DispatchPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mission_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    version: int = Field(ge=1)
    coordinate_frame: Literal["GLOBAL_RELATIVE_ALT"] = "GLOBAL_RELATIVE_ALT"
    waypoints: list[Waypoint] = Field(min_length=1, max_length=200)
    endpoints: dict[int, CompanionEndpoint]

    @model_validator(mode="after")
    def check_endpoints(self):
        if set(self.endpoints) != {3, 4}:
            raise ValueError("Exactly UAV-3 and UAV-4 endpoints are required")
        if self.endpoints[3] == self.endpoints[4]:
            raise ValueError("Companions must have distinct UDP endpoints")
        return self


class DispatchAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(ge=1)
    confirmation: str = ""


class AppendWaypoints(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(ge=1)
    confirmation: Literal["CONFIRM_APPEND"]
    waypoints: list[Waypoint] = Field(min_length=1, max_length=200)


class GeofenceUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    center_lat: float = Field(ge=-90, le=90)
    center_lon: float = Field(ge=-180, le=180)
    radius_m: float = Field(gt=0, le=10000)
