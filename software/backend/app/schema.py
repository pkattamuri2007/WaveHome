"""Pydantic model for the WaveHome CSI packet. Mirrors docs/schema.md (v0.1)."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, model_validator

SCHEMA_VERSION = "0.1"

CsiValue = Annotated[StrictInt, Field(ge=-128, le=127)]


class CSIPacket(BaseModel):
    # Strict types: "5" or 5.0 are rejected rather than coerced to 5.
    model_config = ConfigDict(strict=True)

    schema_version: Literal["0.1"]
    node_id: Annotated[StrictStr, Field(min_length=1)]
    seq: Annotated[StrictInt, Field(ge=0)]
    ts_device_us: Annotated[StrictInt, Field(ge=0)]
    rssi: Annotated[StrictInt, Field(le=0)]
    channel: Annotated[StrictInt, Field(ge=1)]
    bandwidth_mhz: Literal[20, 40]
    csi_len: Annotated[StrictInt, Field(ge=1)]
    csi: list[CsiValue]

    @model_validator(mode="after")
    def csi_len_matches(self) -> "CSIPacket":
        # Not expressible in JSON Schema, so it is enforced here.
        if self.csi_len != len(self.csi):
            raise ValueError(f"csi_len is {self.csi_len} but csi has {len(self.csi)} values")
        return self
