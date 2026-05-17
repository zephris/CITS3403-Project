import pytest
from app import app, db


@pytest.fixture
def client():
    app.config["TESTING"] = True
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    app.config["WTF_CSRF_ENABLED"] = False

    with app.app_context():
        db.create_all()

    with app.test_client() as client:
        yield client

    with app.app_context():
        db.drop_all()


def test_home_page_loads(client):
    response = client.get("/")
    assert response.status_code == 200


def test_singleplayer_redirects_to_game(client):
    response = client.get("/singleplayer", follow_redirects=False)
    assert response.status_code in [302, 308]


def test_lobby_browser_loads(client):
    response = client.get("/browser")
    assert response.status_code == 200