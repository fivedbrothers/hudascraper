"""
hudascraper.hudasconfig
=================================

Configuration dataclasses and helpers used to coerce a JSON configuration
into Python objects consumed by the scraper runtime.

The primary public surface is :class:`Config`, which mirrors the JSON
structure users author. The module also exposes a small helper,
:func:`load_config`, which reads a JSON file and returns a typed
:class:`Config` instance.
"""

import json
from dataclasses import MISSING, dataclass, field, fields, is_dataclass
from pathlib import Path
from typing import Any, Literal, Union, get_args, get_origin


@dataclass
class SelectorCandidate:
    """
    An individual selector candidate.

    A selector candidate is one of the ordered fallbacks attempted when
    resolving an element. It contains the selector string and runtime
    hints such as engine (CSS or XPath), visibility state and timeout.

    Fields
    ------
    selector: CSS or XPath selector string.
    engine: either ``css`` or ``xpath``. Defaults to ``css``.
    state: one of ``attached``, ``visible`` or ``hidden`` describing the
        required DOM state before the element is considered resolved.
    timeout_ms: how long to wait in milliseconds before considering this
        candidate a failure.
    allow_unstable: when True, allows selectors that are heuristically
        considered brittle (not recommended by default).
    multi_match: when True, expects multiple matching elements instead of
        a single match.
    strict: reserved for future enforcement of strict-match semantics.
    """

    selector: str
    engine: Literal["css", "xpath"] = "css"
    state: Literal["attached", "visible", "hidden"] = "attached"
    timeout_ms: int = 10000
    allow_unstable: bool = False
    multi_match: bool = False
    strict: bool = True  # TODO(Mark Dasco): implement handling of this data


@dataclass
class SelectorSet:
    """
    A container for an ordered list of :class:`SelectorCandidate`.

    Selector sets are used in the configuration where a single logical
    element may be located by multiple alternate selectors.
    """

    candidates: list[SelectorCandidate]


@dataclass
class PaginationConfig:
    """
    Configuration for pagination strategies.

    ``strategy`` selects a high-level paginator; the remaining optional
    fields (``next_button``, ``load_more`` etc.) hold strategy-specific
    configuration objects (kept as raw dicts so the JSON config remains
    flexible).
    """

    strategy: Literal["next_button", "load_more", "numbered", "infinite_scroll"] = (
        "next_button"
    )
    next_button: dict | None = None
    load_more: dict | None = None
    numbered: dict | None = None
    infinite_scroll: dict | None = None


@dataclass
class SessionConfig:
    """
    Session and storage_state configuration.

    ``path`` may override the default storage state location. Other fields
    control reuse, saving, and timeouts for login flows.
    """

    path: Path | None = None
    user: str = ""
    site_host: str = ""
    reuse: bool = True
    save_on_success: bool = True
    auth_timeout_s: int = 180
    headed_on_first_run: bool = True  # helpful for manual/MFA


@dataclass
class Config:
    """
    Top-level runtime configuration.

    This dataclass mirrors the keys accepted by the JSON configuration
    files used by the scraper. Users typically author JSON objects that
    are read with :func:`load_config`.
    """

    browser: Literal["chromium", "firefox", "webkit"] = "chromium"
    headless: bool = True
    base_url: str = ""

    session: SessionConfig = field(default_factory=SessionConfig)

    frames: list[dict] = field(default_factory=list)
    wait_targets: list[dict] = field(default_factory=list)
    spinners_to_hide: list[dict] = field(default_factory=list)
    pre_actions: list[dict] = field(default_factory=list)

    selectors: dict = field(default_factory=dict)
    rows_per_page: dict = field(default_factory=dict)
    pagination: PaginationConfig = field(default_factory=PaginationConfig)
    # pagination: PaginationConfig | None = None

    header_strategy: dict = field(default_factory=dict)
    data_normalization: dict = field(default_factory=dict)


def _unwrap_optional(t: Any) -> Any:
    """
    Return the inner type if ``t`` is Optional[...] else ``t``.

    This helper is used when coercing JSON values into typed dataclass
    fields so Optional[...] annotations are handled correctly.
    """
    if get_origin(t) is Union:
        non_none = [a for a in get_args(t) if a is not type(None)]
        if len(non_none) == 1:
            return non_none[0]
    return t


def coerce_value(val: Any, target_type: type[Any]) -> Any:
    # Handle Optional[...]
    inner_type = _unwrap_optional(target_type)

    # Dataclass instance from dict
    if is_dataclass(inner_type) and isinstance(val, dict):
        return coerce_nested(val, inner_type)

    origin = get_origin(inner_type)
    args = get_args(inner_type)

    # List[...] of dataclasses
    if origin in (list, tuple) and args:
        inner_arg = args[0]
        return type(val)(coerce_value(v, inner_arg) for v in val)

    # Dict[..., SomeDataclass]
    if origin is dict and len(args) == 2:
        key_type, value_type = args
        return {
            coerce_value(k, key_type): coerce_value(v, value_type)
            for k, v in val.items()
        }

    # Pass through untouched
    return val


def coerce_nested(obj: dict, cls: type[Any]) -> Any:
    if not is_dataclass(cls):
        return obj

    kwargs = {}
    for f in fields(cls):
        if f.name not in obj:
            continue
        val = obj[f.name]
        if val is MISSING:
            continue
        kwargs[f.name] = coerce_value(val, f.type)

    return cls(**kwargs)


def load_config(path: str | Path) -> Config:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return coerce_nested(raw, Config)
