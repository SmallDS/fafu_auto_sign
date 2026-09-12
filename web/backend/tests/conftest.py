from __future__ import annotations

import os
import tempfile
from collections.abc import Generator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

# Web 模块在导入时解析数据路径，测试必须先指向独立临时目录。
os.environ.setdefault("FAFU_DATA_DIR", tempfile.mkdtemp(prefix="fafu-web-tests-"))

from app.database import Base
import app.models  # noqa: F401 - register mapped tables


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False, autoflush=False) as session:
        yield session
    Base.metadata.drop_all(engine)
    engine.dispose()
