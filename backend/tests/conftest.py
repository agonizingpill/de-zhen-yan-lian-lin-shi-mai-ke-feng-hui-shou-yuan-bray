import os
import tempfile

# 必须在导入应用模块前设置，core.config 在导入时读取环境变量。
_DB_FD, _DB_PATH = tempfile.mkstemp(prefix="drill-venue-", suffix=".db")
os.close(_DB_FD)
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_DB_PATH}")
os.environ.setdefault("REDIS_URL", "redis://127.0.0.1:6399/0")
os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("SEED_DEMO", "false")

import pytest
from fastapi.testclient import TestClient

from core import queueing
from core.db import metadata, engine


class FakePipeline:
    def __init__(self, broker):
        self.broker = broker
        self.ops = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            self.execute()
        return False

    def set(self, key, value, ex=None):
        self.ops.append(("set", key, value))
        return self

    def rpush(self, key, value):
        self.ops.append(("rpush", key, value))
        return self

    def lrem(self, key, count, value):
        self.ops.append(("lrem", key, count, value))
        return self

    def execute(self):
        for op in self.ops:
            getattr(self.broker, op[0])(*op[1:])
        self.ops.clear()
        return True


class FakeRedis:
    """仅实现队列/凭证流程用到的命令，替代真实 Redis。"""

    def __init__(self):
        self.kv = {}
        self.lists = {}

    def ping(self):
        return True

    def pipeline(self):
        return FakePipeline(self)

    def set(self, key, value, ex=None):
        self.kv[key] = value

    def get(self, key):
        return self.kv.get(key)

    def rpush(self, key, value):
        self.lists.setdefault(key, []).append(value)

    def lpop(self, key):
        return self.lists.get(key, []).pop(0) if self.lists.get(key) else None

    def lrem(self, key, count, value):
        if key in self.lists and value in self.lists[key]:
            self.lists[key].remove(value)

    def lrange(self, key, start, end):
        return list(self.lists.get(key, []))


def drain_jobs(broker):
    """直接走真实 worker 的单条处理逻辑，把排队任务跑到 ready/rejected。"""
    from core import worker
    while True:
        item = broker.lpop(queueing.QUEUE)
        if item is None:
            return
        worker.handle_job(item)


@pytest.fixture
def broker(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr(queueing, "broker", fake)
    return fake


@pytest.fixture
def db():
    metadata.drop_all(engine)
    metadata.create_all(engine)
    yield engine
    metadata.drop_all(engine)
    metadata.create_all(engine)


@pytest.fixture
def client(db, broker):
    from core.app import app
    # lifespan 内会跑 migrate + create_all + seed(SEED_DEMO=false)。
    with TestClient(app) as test_client:
        yield test_client


def login(client, role):
    response = client.post("/auth/login",
                           json={"email": f"{role}@demo.test", "password": "DemoC0de!2026"})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['token']}"}


def venue_headers(role_headers, venue):
    return {**role_headers, "X-Venue-Code": venue}
