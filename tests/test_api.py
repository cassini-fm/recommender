import pytest
from fastapi.testclient import TestClient

import main

client = TestClient(main.app)
USER = "11111111-1111-4111-8111-111111111111"

def test_lists_the_modes():
    assert client.get("/modes").json() == {"modes": ["similar", "rediscover"]}

def test_runs_the_chosen_mode(monkeypatch):
    calls = []

    def fake(user, limit):
        calls.append((str(user), limit))
        return [{"artist": "a", "title": "b", "album": None, "mbid": None, "score": 1, "reason": "test"}]

    monkeypatch.setitem(main.MODES, "similar", fake)
    response = client.get("/recommendations", params={"user_id": USER, "mode": "similar", "limit": 5})
    assert response.status_code == 200
    assert response.json()["items"][0]["title"] == "b"
    assert calls == [(USER, 5)]

def test_rejects_an_unknown_mode():
    response = client.get("/recommendations", params={"user_id": USER, "mode": "none"})
    assert response.status_code == 400

@pytest.mark.parametrize("params", [
    {"user_id": "not-a-uuid", "mode": "similar"},
    {"user_id": USER, "mode": "similar", "limit": 0},
    {"user_id": USER, "mode": "similar", "limit": 101},
    {"user_id": USER},
])
def test_rejects_invalid_parameters(params):
    assert client.get("/recommendations", params=params).status_code == 422
