from __future__ import annotations

import os

from app.config.base import Configuration, Group

from . import default

CONF = Configuration()

def configure(project: str, setup: bool = True) -> None:
    conf_modules = (
        (default.GROUP_NAME, default.ALL_OPTS),
    )
    groups = [Group(*item) for item in conf_modules]
    CONF(groups)
    if setup:
        CONF.setup(project, os.environ.copy())

__all__ = ("CONF", "configure")
