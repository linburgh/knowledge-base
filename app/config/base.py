# Copyright 2021 99cloud
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from __future__ import annotations

import re
import warnings
from collections.abc import Iterator, Sequence
from dataclasses import InitVar, dataclass, field
from pathlib import Path, PurePath
from typing import Any, NamedTuple, get_origin

import yaml
from immutables import Map, MapItems, MapKeys, MapValues
from pydantic import BaseModel, StrictBool, StrictInt, create_model


class EnvironmentValue(str):
    """A value resolved from an app.yaml environment placeholder."""


def _resolve_environment_values(value: Any, env: dict[str, str], path: str = "") -> Any:
    if isinstance(value, dict):
        return {
            key: _resolve_environment_values(item, env, f"{path}.{key}".lstrip("."))
            for key, item in value.items()
        }

    if isinstance(value, list):
        return [
            _resolve_environment_values(item, env, f"{path}[{index}]")
            for index, item in enumerate(value)
        ]

    if not isinstance(value, str):
        return value

    pattern = r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}"
    matches = list(re.finditer(pattern, value))
    if not matches:
        return value

    missing = sorted({match.group(1) for match in matches if match.group(1) not in env})
    if missing:
        location = f" at {path}" if path else ""
        names = ", ".join(missing)
        raise ValueError(
            f"Missing environment variable(s) {names} referenced by app.yaml{location}"
        )

    if len(matches) == 1 and matches[0].span() == (0, len(value)):
        return EnvironmentValue(env[matches[0].group(1)])

    resolved = value
    for match in reversed(matches):
        name = match.group(1)
        resolved = resolved[: match.start()] + env[name] + resolved[match.end() :]
    return resolved


def _coerce_environment_value(value: EnvironmentValue, schema: Any) -> Any:
    if schema is StrictBool:
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "on"}:
            return True
        if normalized in {"false", "0", "no", "off"}:
            return False
        raise ValueError(f"Invalid boolean environment value: {value}")

    if schema is StrictInt:
        try:
            return int(value)
        except ValueError as exc:
            raise ValueError(f"Invalid integer environment value: {value}") from exc

    origin = get_origin(schema)
    if origin is list:
        parsed = yaml.safe_load(value)
        if isinstance(parsed, list):
            return parsed
        return [item.strip() for item in value.split(",") if item.strip()]

    return value


class ConfigPath(NamedTuple):
    config_dir_path: str
    config_file_path: str


@dataclass(frozen=True)
class Opt:
    name: str
    description: str
    schema: Any
    default: Any = None
    deprecated: bool = False
    value: Any = field(init=False, default=None)
    _schema_model: type[BaseModel] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "_schema_model",
            create_model(f"Opt(name='{self.name}')", value=(self.schema, ...)),
        )

    def load(self, value: Any) -> None:
        value = self.default if value is None else value
        if isinstance(value, EnvironmentValue):
            value = _coerce_environment_value(value, self.schema)
        self._schema_model(value=value)
        object.__setattr__(self, "value", value)
        if self.deprecated:
            warnings.warn(
                f"The config opt {self.name} is deprecated, will be deleted in the"
                " future version",
                DeprecationWarning,
                stacklevel=2,
            )


@dataclass(repr=False, frozen=True)
class Group:
    name: str
    init_opts: InitVar[Sequence[Opt]] = tuple()
    _opts: Map[str, Opt] = field(init=False, repr=False)

    def __post_init__(self, init_opts: Sequence[Opt]) -> None:
        object.__setattr__(self, "_opts", Map({opt.name: opt for opt in init_opts}))

    def __getattr__(self, name: str) -> Any:
        if name in self._opts:
            return self._opts[name].value
        raise AttributeError(name)

    def __contains__(self, key: Any) -> bool:
        return self._opts.__contains__(key)

    def __iter__(self) -> Iterator[Any]:
        return self._opts.__iter__()

    def __len__(self) -> int:
        return self._opts.__len__()

    def __repr__(self) -> str:
        items = ", ".join(f"{opt}=Opt(name='{opt}')" for opt in self._opts)
        return f"Group({items})"

    def keys(self) -> MapKeys[str]:
        return self._opts.keys()

    def values(self) -> MapValues[Opt]:
        return self._opts.values()

    def items(self) -> MapItems[str, Opt]:
        return self._opts.items()


@dataclass(repr=False, frozen=True)
class Configuration:
    init_groups: InitVar[Sequence[Group]] = tuple()
    config: dict[str, Any] = field(init=False, default_factory=dict, repr=False)
    _groups: Map[str, Group] = field(init=False, repr=False)

    def __post_init__(self, init_groups: Sequence[Group]) -> None:
        object.__setattr__(self, "_groups", Map({group.name: group for group in init_groups}))

    @staticmethod
    def get_config_path(project: str, env: dict[str, str]) -> tuple[str, str]:
        config_dir_path = env.get("OS_CONFIG_DIR", PurePath("/etc", project).as_posix())
        config_file_path = PurePath(config_dir_path).joinpath(f"{project}.yaml").as_posix()
        return ConfigPath(config_dir_path.strip(), config_file_path.strip())

    def setup(self, project: str, env: dict[str, str]) -> None:
        config_dir_path, config_file_path = self.get_config_path(project, env)
        if not Path(config_file_path).exists():
            raise ValueError(f"Not found config file: {config_file_path}")

        with open(config_file_path) as f:
            config = yaml.safe_load(f) or {}
            config = _resolve_environment_values(config, env)
            object.__setattr__(self, "config", config)

        for group in self._groups.values():
            for opt in group._opts.values():
                value = self.config.get(group.name, {}).get(opt.name)
                opt.load(value)

    def cleanup(self) -> None:
        for group in self._groups.values():
            for opt in group._opts.values():
                object.__setattr__(opt, "value", None)
        object.__setattr__(self, "_groups", Map())
        object.__setattr__(self, "config", {})

    def __call__(self, init_groups: Sequence[Group]) -> Any:
        object.__setattr__(self, "_groups", Map({group.name: group for group in init_groups}))

    def __getattr__(self, name: str) -> Group:
        if name in self._groups:
            return self._groups[name]
        raise AttributeError(name)

    def __contains__(self, key: Any) -> bool:
        return self._groups.__contains__(key)

    def __iter__(self) -> Iterator[Any]:
        return self._groups.__iter__()

    def __len__(self) -> int:
        return self._groups.__len__()

    def __repr__(self) -> str:
        items = ", ".join(f"{group}=Group(name='{group}')" for group in self._groups)
        return f"Configuration({items})"

    def keys(self) -> MapKeys[str]:
        return self._groups.keys()

    def values(self) -> MapValues[Group]:
        return self._groups.values()

    def items(self) -> MapItems[str, Group]:
        return self._groups.items()


__all__ = ("Opt", "Group", "Configuration")
