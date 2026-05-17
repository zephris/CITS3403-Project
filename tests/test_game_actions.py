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


def test_singleplayer_game_page_loads(client):
    response = client.get("/singleplayer", follow_redirects=True)

    assert response.status_code == 200
    assert b"Monopoly" in response.data


def test_roll_dice_route_works(client):
    client.get("/singleplayer", follow_redirects=True)

    response = client.post(
        "/roll",
        headers={"X-Requested-With": "XMLHttpRequest"}
    )

    assert response.status_code == 200
    data = response.get_json()

    assert data["ok"] is True
    assert "dice_result" in data
    assert "html" in data