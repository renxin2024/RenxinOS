"""HTTP API 单元测试。"""

from unittest.mock import patch

from fastapi.testclient import TestClient

from src.api import app

client = TestClient(app)


def test_scalar_docs():
    response = client.get("/scalar")
    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")
    assert "Renxin OS" in response.text


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
        "timings": {
            "retrieve_ms": 12.3,
            "prompt_ms": 0.5,
            "llm_ms": 856.0,
            "total_ms": 868.8,
        },
    }

    response = client.post("/chat", json={"question": "什么是4D"})
    assert response.status_code == 200
    data = response.json()
    assert "4D" in data["answer"]
    assert len(data["sources"]) == 1
    assert data["sources"][0]["file"] == "ABC.md"
    assert data["timings"]["retrieve_ms"] == 12.3
    assert data["timings"]["llm_ms"] == 856.0
    assert data["timings"]["total_ms"] == 868.8
    mock_ask.assert_called_once_with("什么是4D", top_k=8)


def test_chat_empty_question():
    response = client.post("/chat", json={"question": "   "})
    assert response.status_code == 400
