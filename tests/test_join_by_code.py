"""
Tests for the join-by-code functionality.
Tests the ability for players to join lobbies using a generated room code.
"""
from pathlib import Path

import pytest
from app import app, db
from models import Lobby, LobbyPlayer, LobbyMessage


@pytest.fixture
def client():
    """Set up a test client with a file-backed SQLite database."""
    app.config["TESTING"] = True
    test_db_path = Path(r"d:\uni\CITS\3403\CITS3403-project\instance\test_join_by_code.db")
    if test_db_path.exists():
        test_db_path.unlink()

    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{test_db_path.as_posix()}"
    app.config["WTF_CSRF_ENABLED"] = False

    with app.app_context():
        db.create_all()

    with app.test_client() as client:
        with client.session_transaction() as session_data:
            session_data["csrf_token"] = "test-csrf-token"
        yield client

    with app.app_context():
        db.drop_all()

    if test_db_path.exists():
        test_db_path.unlink()


def post_form(client, url, data=None, **kwargs):
    """Post a form with the CSRF token expected by the app."""
    payload = dict(data or {})
    payload.setdefault("csrf_token", "test-csrf-token")

    with client.session_transaction() as session_data:
        session_data["csrf_token"] = "test-csrf-token"

    return client.post(url, data=payload, **kwargs)


def create_and_auth_user(client, username, password):
    """Helper function to create and authenticate a user."""
    password = "1234567"

    post_form(client, "/register", {
        "username": username,
        "password": password
    })
    
    post_form(client, "/login", {
        "username": username,
        "password": password
    })


def create_private_lobby(client, username, lobby_name):
    """Helper function to create a private lobby."""
    create_and_auth_user(client, username, "test123")
    
    post_form(client, "/browser/create", {
        "lobby_name": lobby_name,
        "lobby_type": "private",
        "max_players": 4
    })
    
    with app.app_context():
        lobby = Lobby.query.filter_by(name=lobby_name).first()
        assert lobby is not None, "Expected private lobby to be created before join-by-code tests run"
        return lobby


def create_public_lobby(client, username, lobby_name):
    """Helper function to create a public lobby."""
    create_and_auth_user(client, username, "test123")

    post_form(client, "/browser/create", {
        "lobby_name": lobby_name,
        "lobby_type": "public",
        "max_players": 4
    })

    with app.app_context():
        lobby = Lobby.query.filter_by(name=lobby_name).first()
        assert lobby is not None, "Expected public lobby to be created"
        return lobby


def test_join_by_code_button_visible_in_lobby_browser(client):
    """Test that 'Join by Room Code' button is visible in the lobby browser."""
    create_and_auth_user(client, "viewer", "test123")
    
    response = client.get("/browser")
    assert response.status_code == 200
    assert b"Join by Room Code" in response.data


def test_room_code_displayed_in_private_lobby(client):
    """Test that room code is displayed in the waiting lobby for private lobbies."""
    private_lobby = create_private_lobby(client, "hostuser", "Test Private Lobby")
    
    response = client.get(f"/lobby/{private_lobby.id}")
    assert response.status_code == 200
    
    with app.app_context():
        lobby = Lobby.query.get(private_lobby.id)
        assert lobby.invite_code is not None
        assert len(lobby.invite_code) == 8
        # Room code should be in the response
        assert lobby.invite_code in response.data.decode()


def test_join_by_valid_room_code(client):
    """Test that a player can join a lobby using a valid room code."""
    private_lobby = create_private_lobby(client, "hostuser", "Test Private Lobby")
    
    with app.app_context():
        lobby = Lobby.query.get(private_lobby.id)
        room_code = lobby.invite_code
    
    client.get("/logout", follow_redirects=True)
    
    create_and_auth_user(client, "player2", "test123")
    
    response = post_form(client, "/browser/join-by-code", {
        "room_code": room_code
    }, follow_redirects=True)
    
    assert response.status_code == 200
    
    with app.app_context():
        player = LobbyPlayer.query.filter_by(
            lobby_id=private_lobby.id,
            player_name="player2"
        ).first()
        assert player is not None
        assert player.is_ready is False


def test_join_by_code_case_insensitive(client):
    """Test that room code joining is case-insensitive."""
    private_lobby = create_private_lobby(client, "hostuser", "Test Private Lobby")
    
    with app.app_context():
        lobby = Lobby.query.get(private_lobby.id)
        room_code = lobby.invite_code
    
    client.get("/logout", follow_redirects=True)
    
    create_and_auth_user(client, "player3", "test123")
    
    lowercase_code = room_code.lower()
    response = post_form(client, "/browser/join-by-code", {
        "room_code": lowercase_code
    }, follow_redirects=True)
    
    assert response.status_code == 200
    
    with app.app_context():
        player = LobbyPlayer.query.filter_by(
            lobby_id=private_lobby.id,
            player_name="player3"
        ).first()
        assert player is not None


def test_join_by_invalid_room_code(client):
    """Test that joining with an invalid room code returns an error."""
    create_and_auth_user(client, "player4", "test123")
    
    response = post_form(client, "/browser/join-by-code", {
        "room_code": "INVALID12"
    }, follow_redirects=True)
    
    assert response.status_code == 200
    assert b"Invalid room code" in response.data or b"not found" in response.data.lower()


def test_join_by_empty_room_code(client):
    """Test that joining with an empty room code returns an error."""
    create_and_auth_user(client, "player5", "test123")
    
    response = post_form(client, "/browser/join-by-code", {
        "room_code": ""
    }, follow_redirects=True)
    
    assert response.status_code == 200
    assert b"enter a room code" in response.data.lower()


def test_join_by_code_when_lobby_full(client):
    """Test that joining by code fails when the lobby is full."""
    private_lobby = create_private_lobby(client, "hostuser", "Test Private Lobby")
    
    with app.app_context():
        lobby = Lobby.query.get(private_lobby.id)
        room_code = lobby.invite_code
        lobby.max_players = 1
        db.session.commit()
    
    client.get("/logout", follow_redirects=True)
    
    create_and_auth_user(client, "player6", "test123")
    
    response = post_form(client, "/browser/join-by-code", {
        "room_code": room_code
    }, follow_redirects=True)
    
    assert response.status_code == 200
    assert b"full" in response.data.lower()


def test_join_by_code_when_game_in_progress(client):
    """Test that joining by code fails when the game is already in progress."""
    private_lobby = create_private_lobby(client, "hostuser", "Test Private Lobby")
    
    with app.app_context():
        lobby = Lobby.query.get(private_lobby.id)
        room_code = lobby.invite_code
        lobby.status = "in_game"
        db.session.commit()
    
    client.get("/logout", follow_redirects=True)
    
    create_and_auth_user(client, "player7", "test123")
    
    response = post_form(client, "/browser/join-by-code", {
        "room_code": room_code
    }, follow_redirects=True)
    
    assert response.status_code == 200
    assert b"in progress" in response.data.lower()


def test_join_by_code_already_in_lobby(client):
    """Test that a player who is already in the lobby stays in the lobby page."""
    private_lobby = create_private_lobby(client, "hostuser", "Test Private Lobby")
    
    with app.app_context():
        lobby = Lobby.query.get(private_lobby.id)
        room_code = lobby.invite_code
    
    response = post_form(client, "/browser/join-by-code", {
        "room_code": room_code
    }, follow_redirects=True)
    
    assert response.status_code == 200
    assert b"Test Private Lobby" in response.data


def test_join_by_code_creates_system_message(client):
    """Test that a system message is created when a player joins by code."""
    private_lobby = create_private_lobby(client, "hostuser", "Test Private Lobby")
    
    with app.app_context():
        lobby = Lobby.query.get(private_lobby.id)
        room_code = lobby.invite_code
    
    client.get("/logout", follow_redirects=True)
    
    create_and_auth_user(client, "player8", "test123")
    
    response = post_form(client, "/browser/join-by-code", {
        "room_code": room_code
    }, follow_redirects=True)
    
    assert response.status_code == 200
    
    with app.app_context():
        message = LobbyMessage.query.filter_by(
            lobby_id=private_lobby.id,
            sender_name="System"
        ).filter(LobbyMessage.message_text.contains("player8")).first()
        assert message is not None
        assert "room code" in message.message_text.lower()


def test_room_code_format(client):
    """Test that room codes have the correct format (8 uppercase alphanumeric characters)."""
    private_lobby = create_private_lobby(client, "hostuser", "Test Private Lobby")
    
    with app.app_context():
        lobby = Lobby.query.get(private_lobby.id)
        room_code = lobby.invite_code
        
        assert len(room_code) == 8
        assert room_code.isupper()
        assert room_code.isalnum()


def test_room_code_uniqueness(client):
    """Test that each lobby gets a unique room code."""
    create_and_auth_user(client, "hostuser3", "test123")
    
    post_form(client, "/browser/create", {
        "lobby_name": "Lobby 1",
        "lobby_type": "private",
        "max_players": 4
    })
    
    post_form(client, "/browser/create", {
        "lobby_name": "Lobby 2",
        "lobby_type": "private",
        "max_players": 4
    })
    
    with app.app_context():
        lobby1 = Lobby.query.filter_by(name="Lobby 1").first()
        lobby2 = Lobby.query.filter_by(name="Lobby 2").first()
        
        assert lobby1.invite_code != lobby2.invite_code
        assert len(lobby1.invite_code) == 8
        assert len(lobby2.invite_code) == 8


def test_multiple_players_join_by_code(client):
    """Test that multiple players can join the same lobby using its room code."""
    private_lobby = create_private_lobby(client, "hostuser", "Test Private Lobby")
    
    with app.app_context():
        lobby = Lobby.query.get(private_lobby.id)
        room_code = lobby.invite_code
    
    client.get("/logout", follow_redirects=True)
    
    for i in range(3):
        username = f"playermulti{i}"
        create_and_auth_user(client, username, "test123")
        
        response = post_form(client, "/browser/join-by-code", {
            "room_code": room_code
        }, follow_redirects=True)
        
        assert response.status_code == 200
        
        client.get("/logout", follow_redirects=True)
    
    with app.app_context():
        players = LobbyPlayer.query.filter_by(lobby_id=private_lobby.id).all()
        player_names = [p.player_name for p in players]
        
        assert "hostuser" in player_names
        assert "playermulti0" in player_names
        assert "playermulti1" in player_names
        assert "playermulti2" in player_names


def test_join_by_code_without_login(client):
    """Test that joining by code redirects to login if not authenticated."""
    with app.app_context():
        lobby = Lobby(
            name="Test Lobby",
            lobby_type="private",
            host_name="host",
            max_players=4,
            invite_code="TESTCODE"
        )
        db.session.add(lobby)
        db.session.commit()
    
    response = post_form(client, "/browser/join-by-code", {
        "room_code": "TESTCODE"
    }, follow_redirects=True)
    
    assert b"login" in response.data.lower()
