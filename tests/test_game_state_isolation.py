import pytest
import app as app_module


@pytest.fixture
def client():
    app_module.app.config["TESTING"] = True
    app_module.app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"

    with app_module.app.app_context():
        app_module.db.create_all()

    with app_module.app.test_client() as client:
        yield client

    with app_module.app.app_context():
        app_module.db.drop_all()


def test_game_contexts_exist():
    """
    The app should now store game states by game_id instead of using only one
    shared global game_state.
    """
    assert hasattr(app_module, "game_contexts")
    assert isinstance(app_module.game_contexts, dict)


def test_multiple_game_ids_have_separate_contexts(client):
    """
    This test checks that two different game_id values do not share the same
    game_state, game_log, property_houses, chat messages, or restart_votes.
    """

    app_module.game_contexts.clear()

    players_a = [
        {"player_id": "player1", "name": "Alice"},
        {"player_id": "ai_1", "name": "AI A"},
    ]

    players_b = [
        {"player_id": "player1", "name": "Bob"},
        {"player_id": "ai_1", "name": "AI B"},
    ]

    game_a_id = "test_game_a"
    game_b_id = "test_game_b"

    # Create two independent game contexts.
    app_module.game_contexts[game_a_id] = {
        "game_state": app_module.engine.initialize_game(players_a),
        "game_log": ["Game A started."],
        "game_chat_messages": [],
        "property_houses": {},
        "property_landing_counts": {},
        "restart_votes": set(),
        "current_game_players": players_a,
        "last_roll": None,
        "can_buy": False,
        "game_over": False,
        "waiting_for_ai": False,
        "pending_buy_player_id": None,
        "pending_buy_tile_index": None,
    }

    app_module.game_contexts[game_b_id] = {
        "game_state": app_module.engine.initialize_game(players_b),
        "game_log": ["Game B started."],
        "game_chat_messages": [],
        "property_houses": {},
        "property_landing_counts": {},
        "restart_votes": set(),
        "current_game_players": players_b,
        "last_roll": None,
        "can_buy": False,
        "game_over": False,
        "waiting_for_ai": False,
        "pending_buy_player_id": None,
        "pending_buy_tile_index": None,
    }

    # Mutate only game A.
    app_module.game_contexts[game_a_id]["game_log"].append("Only Game A changed.")
    app_module.game_contexts[game_a_id]["game_chat_messages"].append({
        "sender": "Alice",
        "text": "Hello from Game A"
    })
    app_module.game_contexts[game_a_id]["property_houses"][1] = 2
    app_module.game_contexts[game_a_id]["restart_votes"].add("player1")
    app_module.game_contexts[game_a_id]["game_state"].players["player1"].cash = 999

    # Game B should not be affected.
    assert "Only Game A changed." not in app_module.game_contexts[game_b_id]["game_log"]
    assert app_module.game_contexts[game_b_id]["game_chat_messages"] == []
    assert app_module.game_contexts[game_b_id]["property_houses"] == {}
    assert app_module.game_contexts[game_b_id]["restart_votes"] == set()
    assert app_module.game_contexts[game_b_id]["game_state"].players["player1"].cash != 999

    # Also check that the two game_state objects are not the same object.
    assert (
        app_module.game_contexts[game_a_id]["game_state"]
        is not app_module.game_contexts[game_b_id]["game_state"]
    )