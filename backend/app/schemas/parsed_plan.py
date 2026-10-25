import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from pydantic import RootModel, model_validator

SCHEMA_PATH = Path(__file__).resolve().parents[3] / "ai" / "schema.json"


@lru_cache(maxsize=1)
def _schema() -> dict[str, Any]:
    with SCHEMA_PATH.open(encoding="utf-8") as schema_file:
        schema = json.load(schema_file)
    Draft202012Validator.check_schema(schema)
    return schema


@lru_cache(maxsize=1)
def _validator() -> Draft202012Validator:
    return Draft202012Validator(_schema())


class ParsedPlan(RootModel[dict[str, Any]]):
    """Validated ParsedPlan whose constraints are loaded from ai/schema.json."""

    @model_validator(mode="before")
    @classmethod
    def validate_against_source_schema(cls, value: Any) -> Any:
        errors = sorted(
            _validator().iter_errors(value),
            key=lambda error: tuple(map(str, error.absolute_path)),
        )
        if errors:
            details = "; ".join(
                f"{'.'.join(map(str, error.absolute_path)) or '<root>'}: {error.message}"
                for error in errors
            )
            raise ValueError(f"ParsedPlan does not match ai/schema.json: {details}")
        return value

    @classmethod
    def __get_pydantic_json_schema__(cls, core_schema: Any, handler: Any) -> dict[str, Any]:
        # ParsedPlan is the root document; auxiliary endpoint schemas in $defs
        # are consumed by API documentation but must not become part of this
        # standalone model's generated JSON Schema.
        schema = dict(_schema())
        schema.pop("$defs", None)
        return schema
