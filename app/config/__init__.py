from __future__ import annotations

import os

from app.config.base import Configuration, Group

from . import default


CONF = Configuration()


def configure(project: str = "app", setup: bool = True) -> Configuration:
    conf_modules = (
        (default.GROUP_NAME, default.ALL_OPTS),
    )
    groups = [Group(*item) for item in conf_modules]
    CONF(groups)
    if setup:
        CONF.setup(project, os.environ.copy())
    else:
        for group in CONF.values():
            for opt in group.values():
                opt.load(None)
    return CONF


configure(setup=False)

__all__ = ("CONF", "configure")
