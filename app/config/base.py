from __future__ import annotations

import warnings
from dataclasses import InitVar, dataclass, field
from pathlib import Path, PurePath
from typing import Any, Iterator, NamedTuple, Sequence, Type

import yaml
from pydantic import BaseModel, create_model


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
    _schema_model: Type[BaseModel] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "_schema_model",
            create_model(f"Opt(name='{self.name}')", value=(self.schema, ...)),
        )

    def load(self, value: Any) -> None:
        value = self.default if value is None else value
        self._schema_model(value=value)
        object.__setattr__(self, "value", value)
        if self.deprecated:
            warnings.warn(
                f"The config opt {self.name} is deprecated and will be deleted in a future version",
                DeprecationWarning,
                stacklevel=2,
            )


@dataclass(repr=False, frozen=True)
class Group:
    name: str
    init_opts: InitVar[Sequence[Opt]] = tuple()
    _opts: dict[str, Opt] = field(init=False, repr=False)

    def __post_init__(self, init_opts: Sequence[Opt]) -> None:
        object.__setattr__(self, "_opts", {opt.name: opt for opt in init_opts})

    def __getattr__(self, name: str) -> Any:
        if name in self._opts:
            return self._opts[name].value
        raise AttributeError(name)

    def __contains__(self, key: Any) -> bool:
        return key in self._opts

    def __iter__(self) -> Iterator[str]:
        return iter(self._opts)

    def __len__(self) -> int:
        return len(self._opts)

    def __repr__(self) -> str:
        items = ", ".join(f"{opt}=Opt(name='{opt}')" for opt in self._opts)
        return f"Group({items})"

    def keys(self):
        return self._opts.keys()

    def values(self):
        return self._opts.values()

    def items(self):
        return self._opts.items()


@dataclass(repr=False, frozen=True)
class Configuration:
    init_groups: InitVar[Sequence[Group]] = tuple()
    config: dict[str, Any] = field(init=False, default_factory=dict, repr=False)
    _groups: dict[str, Group] = field(init=False, repr=False)

    def __post_init__(self, init_groups: Sequence[Group]) -> None:
        object.__setattr__(self, "_groups", {group.name: group for group in init_groups})

    @staticmethod
    def get_config_path(project: str, env: dict[str, str]) -> ConfigPath:
        config_dir_path = env.get("OS_CONFIG_DIR", PurePath("/etc", project).as_posix())
        config_file_path = PurePath(config_dir_path).joinpath(f"{project}.yaml").as_posix()
        return ConfigPath(config_dir_path.strip(), config_file_path.strip())

    def setup(self, project: str, env: dict[str, str]) -> None:
        config_dir_path, config_file_path = self.get_config_path(project, env)
        config_path = Path(config_file_path)
        if not config_path.exists():
            example_path = Path(config_dir_path) / f"{project}.yaml.example"
            if example_path.exists():
                config_path = example_path
            elif Path("etc", f"{project}.yaml.example").exists():
                config_path = Path("etc", f"{project}.yaml.example")
            else:
                raise ValueError(f"Not found config file: {config_file_path}")

        with config_path.open("r", encoding="utf-8") as fp:
            try:
                config = yaml.safe_load(fp) or {}
            except Exception as exc:
                raise ValueError("Load config file error") from exc
        object.__setattr__(self, "config", config)

        for group in self._groups.values():
            group_config = self.config.get(group.name, {})
            for opt in group.values():
                opt.load(group_config.get(opt.name))

    def cleanup(self) -> None:
        for group in self._groups.values():
            for opt in group.values():
                object.__setattr__(opt, "value", None)
        object.__setattr__(self, "_groups", {})
        object.__setattr__(self, "config", {})

    def __call__(self, init_groups: Sequence[Group]) -> Any:
        object.__setattr__(self, "_groups", {group.name: group for group in init_groups})

    def __getattr__(self, name: str) -> Group:
        if name in self._groups:
            return self._groups[name]
        raise AttributeError(name)

    def __contains__(self, key: Any) -> bool:
        return key in self._groups

    def __iter__(self) -> Iterator[str]:
        return iter(self._groups)

    def __len__(self) -> int:
        return len(self._groups)

    def __repr__(self) -> str:
        items = ", ".join(f"{group}=Group(name='{group}')" for group in self._groups)
        return f"Configuration({items})"

    def keys(self):
        return self._groups.keys()

    def values(self):
        return self._groups.values()

    def items(self):
        return self._groups.items()


__all__ = ("Opt", "Group", "Configuration")
