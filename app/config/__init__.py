from __future__ import annotations

import os

from dotenv import load_dotenv

from app.config.base import Configuration, Group

from . import agent, chat, default, embedding, rag, storage

CONF = Configuration()


def configure(project: str, setup: bool = True) -> None:
    conf_modules = (
        (default.GROUP_NAME, default.ALL_OPTS),
        (storage.GROUP_NAME, storage.ALL_OPTS),
        (chat.GROUP_NAME, chat.ALL_OPTS),
        (embedding.GROUP_NAME, embedding.ALL_OPTS),
        (rag.GROUP_NAME, rag.ALL_OPTS),
        (agent.GROUP_NAME, agent.ALL_OPTS),
    )
    groups = [Group(*item) for item in conf_modules]
    CONF(groups)
    if setup:
        load_dotenv(override=False)
        CONF.setup(project, os.environ.copy())

__all__ = ("CONF", "configure")
