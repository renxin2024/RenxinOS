"""HTTP API 单元测试。"""

from unittest.mock import patch

from fastapi.testclient import TestClient

from src.api import app

client = TestClient(app)


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@patch("src.api.ask_agent_with_meta")
def test_chat(mock_ask):
    mock_ask.return_value = {
        "answer": "4D 是 Delete / Delegate / Do / Defer。",
        "sources": [
            {"file": "ABC.md", "heading": "4D", "score": 5},
        ],
    }

    response = client.post("/chat", json={"question": "什么是4D"})
    assert response.status_code == 200
    data = response.json()
    assert "4D" in data["answer"]
    assert len(data["sources"]) == 1
    assert data["sources"][0]["file"] == "ABC.md"
    mock_ask.assert_called_once_with("什么是4D", top_k=8)


def test_chat_empty_question():
    response = client.post("/chat", json={"question": "   "})
    assert response.status_code == 400
