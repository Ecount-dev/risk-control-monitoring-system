"""pytest 公共夹具：为每个测试创建隔离的应用和基础账户。"""

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.repositories.memory import InMemoryDatabase


@pytest.fixture
def client() -> TestClient:
    """每个测试使用全新内存数据库，避免测试顺序影响结果。"""
    app = create_app(InMemoryDatabase())
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def account_id(client: TestClient) -> str:
    """创建常用的默认账户，并把 ID 提供给需要它的测试。"""
    response = client.post(
        "/api/v1/accounts",
        json={"name": "demo-account", "initial_balance": "100000.00"},
    )
    assert response.status_code == 201
    return response.json()["id"]
