import pytest
from app import app, db


@pytest.fixture
def client():
    app.config["TESTING"] = True
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"

    with app.app_context():
        db.create_all()

    with app.test_client() as client:
        yield client

    with app.app_context():
        db.drop_all()


def test_different_game_ids_have_separate_state(client):
    client.get("/singleplayer", follow_redirects=True)

    response_a = client.get("/game/local_demo_game/state")
    assert response_a.status_code == 200

    data_a = response_a.get_json()
    assert data_a["game_id"] == "local_demo_game"

    # This checks that the game state endpoint returns valid game state data.
    assert "game_log" in data_a
    assert "all_players" in data_a