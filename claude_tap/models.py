"""Application-owned Pydantic models and explicit dynamic JSON boundaries."""

from __future__ import annotations

from typing import TypeAlias, TypeVar

from pydantic import BaseModel, ConfigDict, Field
from typing_extensions import TypeAliasType

JsonScalar: TypeAlias = None | bool | int | float | str
JsonValue = TypeAliasType("JsonValue", JsonScalar | list["JsonValue"] | dict[str, "JsonValue"])
JsonObject: TypeAlias = dict[str, JsonValue]
MapKey = TypeVar("MapKey")
MapValue = TypeVar("MapValue")
Map: TypeAlias = dict[MapKey, MapValue]


class PromptToolModel(BaseModel):
    """Normalized tool metadata owned by the prompt snapshot feature."""

    model_config = ConfigDict(frozen=True)

    name: str
    description: str = ""
    schema_: JsonObject = Field(default_factory=dict, alias="schema")
    raw: JsonObject = Field(default_factory=dict)

    @property
    def schema(self) -> JsonObject:
        """Return the provider tool schema without shadowing Pydantic internals."""
        return self.schema_


class PromptSnapshotModel(BaseModel):
    """Stable, serialized representation of a provider prompt snapshot."""

    model_config = ConfigDict(frozen=True)

    provider: str
    model: str
    system_prompt: str = ""
    developer_prompt: str = ""
    user_message: str = ""
    tools: tuple[PromptToolModel, ...] = ()
    turn: int | None = None
    request_id: str = ""
    path: str = ""
    upstream_base_url: str = ""
    captured_at: str = ""
    raw_request_body: JsonObject = Field(default_factory=dict)
