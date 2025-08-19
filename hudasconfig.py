import json
from dataclasses import MISSING, dataclass, field, fields, is_dataclass
from pathlib import Path
from typing import Any, Literal, Union, get_args, get_origin


@dataclass
class SelectorCandidate:
    selector: str
    engine: Literal["css", "xpath"] = "css"
    state: Literal["attached", "visible", "hidden"] = "attached"
    timeout_ms: int = 10000
    allow_unstable: bool = False
    multi_match: bool = False
    strict: bool = True  # TODO(Mark Dasco): implement handling of this data


@dataclass
class SelectorSet:
    candidates: list[SelectorCandidate]


@dataclass
class PaginationConfig:
    strategy: Literal["next_button", "load_more", "numbered", "infinite_scroll"] = (
        "next_button"
    )
    next_button: dict | None = None
    load_more: dict | None = None
    numbered: dict | None = None
    infinite_scroll: dict | None = None


@dataclass
class SessionConfig:
    path: Path | None = None
    user: str = ""
    site_host: str = ""
    reuse: bool = True
    save_on_success: bool = True
    auth_timeout_s: int = 180
    headed_on_first_run: bool = True  # helpful for manual/MFA


@dataclass
class Config:
    browser: Literal["chromium", "firefox", "webkit"] = "chromium"
    headless: bool = True
    base_url: str = ""

    session: SessionConfig = field(default_factory=SessionConfig)

    frames: list[dict] = field(default_factory=list)
    wait_targets: list[dict] = field(default_factory=list)
    spinners_to_hide: list[dict] = field(default_factory=list)

    selectors: dict = field(default_factory=dict)
    rows_per_page: dict = field(default_factory=dict)
    pagination: PaginationConfig = field(default_factory=PaginationConfig)
    # pagination: PaginationConfig | None = None

    header_strategy: dict = field(default_factory=dict)
    data_normalization: dict = field(default_factory=dict)


def _unwrap_optional(t: Any) -> Any:
    """If t is Optional[X], return X, else return t."""
    if get_origin(t) is Union:
        non_none = [a for a in get_args(t) if a is not type(None)]
        if len(non_none) == 1:
            return non_none[0]
    return t

def _coerce_value(val: Any, target_type: type[Any]) -> Any:
    # Handle Optional[...] 
    inner_type = _unwrap_optional(target_type)

    # Dataclass instance from dict
    if is_dataclass(inner_type) and isinstance(val, dict):
        return _coerce_nested(val, inner_type)

    origin = get_origin(inner_type)
    args = get_args(inner_type)

    # List[...] of dataclasses
    if origin in (list, tuple) and args:
        inner_arg = args[0]
        return type(val)(
            _coerce_value(v, inner_arg) for v in val
        )

    # Dict[..., SomeDataclass]
    if origin is dict and len(args) == 2:
        key_type, value_type = args
        return {
            _coerce_value(k, key_type): _coerce_value(v, value_type)
            for k, v in val.items()
        }

    # Pass through untouched
    return val

def _coerce_nested(obj: dict, cls: type[Any]) -> Any:
    if not is_dataclass(cls):
        return obj

    kwargs = {}
    for f in fields(cls):
        if f.name not in obj:
            continue
        val = obj[f.name]
        if val is MISSING:
            continue
        kwargs[f.name] = _coerce_value(val, f.type)

    return cls(**kwargs)

def load_config(path: str | Path) -> Config:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return _coerce_nested(raw, Config)
