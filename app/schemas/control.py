"""Flight-control, mission, and parameter API contracts."""

from __future__ import annotations

from typing import Literal, Optional, Union

from pydantic import BaseModel, Field, field_validator


class ArmDisarmRequest(BaseModel):
    """Optional safety override for an arm or disarm command."""

    force: bool = False


class ModeChangeRequest(BaseModel):
    """Requested autopilot flight mode."""

    mode: str = Field(min_length=1)


class GotoRequest(BaseModel):
    """Global coordinate target for a guided/goto command."""

    latitude_deg: float = Field(ge=-90.0, le=90.0)
    longitude_deg: float = Field(ge=-180.0, le=180.0)
    altitude_m: float


class TakeoffRequest(BaseModel):
    """Relative target altitude for a takeoff command."""

    altitude_m: float = Field(gt=0.0)


class MissionItem(BaseModel):
    """One mission item represented with human-readable global coordinates."""

    seq: int = Field(ge=0)
    command: int = Field(ge=0)
    command_name: Optional[str] = None
    frame: int = Field(ge=0)
    frame_name: Optional[str] = None
    lat: float = Field(ge=-90.0, le=90.0)
    lon: float = Field(ge=-180.0, le=180.0)
    alt: float
    param1: float = 0.0
    param2: float = 0.0
    param3: float = 0.0
    param4: float = 0.0
    current: bool = False
    autocontinue: bool = True


class MissionUploadRequest(BaseModel):
    """Ordered mission items to upload to one UAV."""

    items: list[MissionItem] = Field(min_length=1, max_length=1000)

    @field_validator("items")
    @classmethod
    def require_finite_coordinates(
        cls,
        items: list[MissionItem],
    ) -> list[MissionItem]:
        """Reject NaN and infinite values before they reach pymavlink."""
        numeric_fields = (
            "lat",
            "lon",
            "alt",
            "param1",
            "param2",
            "param3",
            "param4",
        )
        for item in items:
            for field_name in numeric_fields:
                value = getattr(item, field_name)
                if not (-float("inf") < value < float("inf")):
                    raise ValueError(
                        f"mission item {item.seq} contains a non-finite "
                        f"{field_name}",
                    )
        return items


class MissionUploadResponse(BaseModel):
    """Final result of a mission-protocol upload."""

    slot: int = Field(ge=1, le=4)
    success: bool
    total: int = Field(ge=0)
    sent: int = Field(ge=0)
    result_code: Optional[int] = None
    result_label: str
    message: str


class CommandAckResponse(BaseModel):
    """Normalized command acknowledgement reserved for future controls."""

    slot: int = Field(ge=1, le=4)
    command_id: int
    result_code: int
    result_label: str
    accepted: bool
    message: Optional[str] = None


ParamScalar = Union[int, float]


class ParamValue(BaseModel):
    """One decoded MAVLink autopilot parameter."""

    param_id: str = Field(min_length=1, max_length=16)
    type: int = Field(ge=0)
    type_name: str
    value: ParamScalar
    index: int
    count: int = Field(ge=0)


class ParamSetRequest(BaseModel):
    """Requested replacement value for one autopilot parameter."""

    value: float
    param_type: Optional[int] = Field(default=None, ge=0)


class ParamSetResponse(BaseModel):
    """Confirmed result of one PARAM_SET transaction."""

    slot: int = Field(ge=1, le=4)
    success: bool
    param_id: str
    old_value: Optional[ParamScalar] = None
    requested_value: ParamScalar
    confirmed_value: Optional[ParamScalar] = None
    type: int
    type_name: str
    message: str


ParamFetchStatus = Literal[
    "idle",
    "fetching",
    "retrying",
    "complete",
    "incomplete",
    "error",
]


class ParamFetchProgress(BaseModel):
    """Progress snapshot for a parameter-list synchronization."""

    slot: int = Field(ge=1, le=4)
    status: ParamFetchStatus
    received: int = Field(ge=0)
    total: int = Field(ge=0)
    missing_indices: list[int] = Field(default_factory=list)
    parameter: Optional[ParamValue] = None
    message: Optional[str] = None


class ParamSnapshot(ParamFetchProgress):
    """Current parameter cache and synchronization state for one slot."""

    parameters: list[ParamValue] = Field(default_factory=list)
