from flask import Flask, render_template, redirect, url_for
from template.backend.app.game_logic.engine import load_game_config, GameEngine
import random

app = Flask(__name__)
app.secret_key = "dev-secret-key"

config = load_game_config("template/backend/app/game_logic/data/monopoly_standard.json")
engine = GameEngine(config)

players = [
    {"player_id": "player1", "name": "Player 1"},
    {"player_id": "ai_1", "name": "AI Player"}
]

# Temporary local ID for this prototype.
# Later, replace this with the real game_id returned by POST /lobbies/{lobby_id}/start.
game_id = "local_demo_game"

game_state = engine.initialize_game(players)
game_log = ["Game started! Player 1 is on GO."]
last_roll = None
can_buy = False
game_over = False
waiting_for_ai = False


def decision_provider(player_id, action, context):
    if action == "buy_property":
        if player_id.startswith("ai"):
            return {"buy": random.choice([True, False])}

        return {"buy": False}

    if action == "auction_bid":
        return {"bid": False}

    if action == "jail_action":
        return {"choice": "roll"}

    return {}


def get_player():
    return game_state.players["player1"]


def get_current_tile():
    player = get_player()
    return config.tiles[player.pos]


def format_player_name(player_id):
    if player_id == "player1":
        return "Player 1"
    if player_id == "player2":
        return "Player 2"
    if player_id and player_id.startswith("ai"):
        return "AI Player"
    return "System"


def format_event(event):
    event_type = event.get("type", "unknown")
    player_id = event.get("player_id") or event.get("from") or event.get("to")
    name = format_player_name(player_id)

    if event_type == "property_bought":
        return f"{name} bought {event.get('tile')}."

    if event_type == "rent_paid":
        return (
            f"{format_player_name(event.get('from'))} paid "
            f"${event.get('amount')} rent to "
            f"{format_player_name(event.get('to'))} for {event.get('tile')}."
        )

    if event_type == "tax_paid":
        return f"{name} paid ${event.get('amount')} tax."

    if event_type == "card_drawn":
        return f"{name} drew a card: {event.get('description')}"

    if event_type == "landed_own_property":
        return f"{name} landed on their own property: {event.get('tile')}."

    if event_type == "auction":
        return ""

    if event_type == "no_action":
        return f"{name} landed on {event.get('tile')}."

    if event_type == "skip_bankrupt":
        return f"{name} is bankrupt and skipped their turn."

    if event_type == "go_to_jail_double":
        return f"{name} rolled doubles three times and went to jail."

    if event_type == "jail_roll_failed":
        return f"{name} failed to roll doubles and remains in jail."

    if event_type == "jail_roll_doubles":
        return f"{name} rolled doubles and got out of jail."

    if event_type == "jail_release":
        return f"{name} was released from jail and continued their turn."

    if event_type == "jail_forced_release":
        return f"{name} paid ${event.get('fine')} and was released from jail."

    if event_type == "jail_used_card":
        return f"{name} used a Get Out of Jail Free card."

    if event_type == "card_none":
        return f"{name} landed on a card space, but no card was available."

    return f"{name}: {event_type}"


def record_event(event_type, amount=0, metadata=None):
    """
    Temporary local event recorder.
    Later this can be connected to POST /stats/events.
    """
    if metadata is None:
        metadata = {}

    print({
        "game_id": game_id,
        "event_type": event_type,
        "amount": amount,
        "metadata": metadata
    })


def finalize_game():
    """
    Temporary local finalize function.
    Later this can be connected to POST /stats/games/{game_id}/finalize.
    """
    player = game_state.players["player1"]
    ai_player = game_state.players["ai_1"]

    result = {
        "game_id": game_id,
        "winner_user_id": game_state.winner_id,
        "player_results": [
            {
                "user_id": "player1",
                "final_rank": 1 if game_state.winner_id == "player1" else 2,
                "bankrupt_flag": getattr(player, "bankrupt", False),
                "turns_taken": getattr(player, "turns_taken", 0)
            },
            {
                "user_id": "ai_1",
                "final_rank": 1 if game_state.winner_id == "ai_1" else 2,
                "bankrupt_flag": getattr(ai_player, "bankrupt", False),
                "turns_taken": getattr(ai_player, "turns_taken", 0)
            }
        ]
    }

    print(result)


def update_buy_status():
    global can_buy

    player = get_player()
    tile = get_current_tile()

    can_buy = False

    if tile.tile_type == "property":
        property_state = game_state.properties[tile.index]
        if property_state.owner_id is None and player.cash >= tile.buy_price:
            can_buy = True


def check_game_over():
    global game_over

    if game_state.winner_id and not game_over:
        game_over = True
        game_log.append(f"Game over! Winner: {format_player_name(game_state.winner_id)}")
        finalize_game()


def play_ai_turns_until_player():
    """
    Let AI players take their turns until control returns to Player 1.
    This avoids using JavaScript auto-refresh to repeatedly submit /roll.
    """
    safety_counter = 0

    while (
        not game_over
        and game_state.turn_order[game_state.current_turn_index] != "player1"
        and safety_counter < 20
    ):
        acting_player_id = game_state.turn_order[game_state.current_turn_index]
        ai_event = engine.take_turn(game_state, decision_provider)

        if "player_id" not in ai_event:
            ai_event["player_id"] = acting_player_id

        text = format_event(ai_event)

        if text and "landed on GO" not in text:
            game_log.append(text)

        check_game_over()
        safety_counter += 1


def render_game_page(dice_result=None):
    player = get_player()
    tile = get_current_tile()

    property_price = 0
    owner = None

    if tile.tile_type == "property":
        property_price = tile.buy_price
        owner_id = game_state.properties[tile.index].owner_id
        owner = format_player_name(owner_id) if owner_id else None

    ai_player = game_state.players["ai_1"]
    ai_position = ai_player.pos

    property_owners = {}

    for tile_index, property_state in game_state.properties.items():
        property_owners[tile_index] = property_state.owner_id

    return render_template(
        "index.html",
        position=player.pos,
        location=tile.name,
        waiting_for_ai=waiting_for_ai,
        money=player.cash,
        ai_money=ai_player.cash,
        ai_position=ai_position,
        dice_result=dice_result,
        game_log=game_log,
        can_buy=can_buy,
        property_price=property_price,
        owner=owner,
        game_over=game_over,
        winner=format_player_name(game_state.winner_id) if game_state.winner_id else None,
        current_turn=format_player_name(
            game_state.turn_order[game_state.current_turn_index]
        ),
        property_owners=property_owners,
        game_id=game_id,
        is_online=False,
        player_id="player1",
        player_label="Player 1",
        other_player_label="AI Player",
        is_my_turn=(game_state.turn_order[game_state.current_turn_index] == "player1"),
        roll_action=url_for("roll_dice"),
        buy_action=url_for("buy_property"),
        skip_buy_action=url_for("skip_buy"),
        reset_action=url_for("reset_game"),
        leave_action=url_for("lobby_page"),
        auto_refresh=False,
        online_status_message=None
    )



@app.route("/")
def home():
    # Show the mode selection lobby first.
    return redirect(url_for("lobby_page"))


@app.route("/lobby")
def lobby_page():
    return render_template("waiting_lobby.html")


@app.route("/lobby/start", methods=["POST"])
def start_lobby_game():
    global game_state, game_log, last_roll, can_buy, game_over, waiting_for_ai, game_id

    game_id = "local_demo_game"
    game_state = engine.initialize_game(players)
    game_log = ["Game started! Player 1 is on GO."]
    last_roll = None
    can_buy = False
    game_over = False
    waiting_for_ai = False

    return redirect(url_for("game_page", game_id=game_id))


@app.route("/game/<game_id>")
def game_page(game_id):
    # Original local prototype route: Player 1 vs AI.
    update_buy_status()
    return render_game_page()


@app.route("/roll", methods=["POST"])
def roll_dice():
    global last_roll, can_buy, waiting_for_ai

    if game_over:
        return redirect(url_for("game_page", game_id=game_id))

    if waiting_for_ai:
        return redirect(url_for("game_page", game_id=game_id))

    can_buy = False

    old_position = get_player().pos

    acting_player_id = game_state.turn_order[game_state.current_turn_index]
    event = engine.take_turn(game_state, decision_provider)

    if "player_id" not in event:
        event["player_id"] = acting_player_id

    new_position = get_player().pos
    last_roll = (new_position - old_position) % len(config.tiles)

    text = format_event(event)

    if text:
        game_log.append(text)

    update_buy_status()
    check_game_over()

    if not game_over and not can_buy:
        waiting_for_ai = True

    return redirect(url_for("game_page", game_id=game_id))


@app.route("/buy", methods=["POST"])
def buy_property():
    global can_buy, waiting_for_ai

    if game_over:
        return redirect(url_for("game_page", game_id=game_id))

    player = get_player()
    tile = get_current_tile()

    if tile.tile_type == "property":
        property_state = game_state.properties[tile.index]

        if property_state.owner_id is None and player.cash >= tile.buy_price:
            player.cash -= tile.buy_price
            property_state.owner_id = "player1"
            game_log.append(f"Player 1 bought {tile.name} for ${tile.buy_price}.")
            record_event(
                "property_bought",
                amount=tile.buy_price,
                metadata={"player_id": "player1", "tile": tile.name}
            )
        else:
            game_log.append(f"Player 1 cannot buy {tile.name}.")

    can_buy = False
    waiting_for_ai = True

    play_ai_turns_until_player()
    update_buy_status()

    return redirect(url_for("game_page", game_id=game_id))


@app.route("/skip-buy", methods=["POST"])
def skip_buy():
    global can_buy, waiting_for_ai

    tile = get_current_tile()
    game_log.append(f"Player 1 chose not to buy {tile.name}.")
    can_buy = False
    waiting_for_ai = True

    return redirect(url_for("game_page", game_id=game_id))


@app.route("/ai-turn", methods=["POST"])
def ai_turn():
    global waiting_for_ai, can_buy

    if game_over:
        return redirect(url_for("game_page", game_id=game_id))

    can_buy = False

    while game_state.turn_order[game_state.current_turn_index] != "player1":
        acting_player_id = game_state.turn_order[game_state.current_turn_index]
        ai_event = engine.take_turn(game_state, decision_provider)

        if "player_id" not in ai_event:
            ai_event["player_id"] = acting_player_id

        text = format_event(ai_event)

        if text and "landed on GO" not in text:
            game_log.append(text)

        check_game_over()

        if game_over:
            waiting_for_ai = False
            return redirect(url_for("game_page", game_id=game_id))

    waiting_for_ai = False
    update_buy_status()

    return redirect(url_for("game_page", game_id=game_id))


@app.route("/reset", methods=["POST"])
def reset_game():
    global game_state, game_log, last_roll, can_buy, game_over, waiting_for_ai

    game_state = engine.initialize_game(players)
    game_log = ["Game reset! Player 1 is on GO."]
    last_roll = None
    can_buy = False
    game_over = False
    waiting_for_ai = False

    return redirect(url_for("game_page", game_id=game_id))


# -----------------------------------------------------------------------------
# Temporary online multiplayer demo
# -----------------------------------------------------------------------------
# This is intentionally in-memory and temporary. It lets the game part be tested
# before the final user account and lobby system is finished.
online_games = {}


def online_players():
    return [
        {"player_id": "player1", "name": "Player 1"},
        {"player_id": "player2", "name": "Player 2"},
    ]


def online_decision_provider(player_id, action, context):
    # In the temporary online mode, buying is handled by the separate /buy route.
    # Returning False here lets the move finish, then the current player chooses Buy/Skip.
    if action == "buy_property":
        return {"buy": False}
    if action == "auction_bid":
        return {"bid": False}
    if action == "jail_action":
        return {"choice": "roll"}
    return {}


def create_online_game(game_id="demo"):
    online_engine = GameEngine(config)
    online_games[game_id] = {
        "engine": online_engine,
        "state": online_engine.initialize_game(online_players()),
        "log": ["Temporary online multiplayer game started."],
        "last_roll": None,
        "game_over": False,
        "pending_buy_player_id": None,
        "pending_buy_tile_index": None,
    }
    return online_games[game_id]


def get_online_game(game_id="demo"):
    if game_id not in online_games:
        return create_online_game(game_id)
    return online_games[game_id]


def current_turn_id(state):
    return state.turn_order[state.current_turn_index]


def online_check_game_over(game):
    if game["state"].winner_id and not game["game_over"]:
        game["game_over"] = True
        game["log"].append(f"Game over! Winner: {format_player_name(game['state'].winner_id)}")


def online_property_can_be_bought(game, player_id):
    state = game["state"]
    pending_player = game.get("pending_buy_player_id")
    pending_tile_index = game.get("pending_buy_tile_index")

    if pending_player != player_id or pending_tile_index is None:
        return False

    tile = config.tiles[pending_tile_index]
    if tile.tile_type != "property":
        return False

    property_state = state.properties[tile.index]
    return property_state.owner_id is None and state.players[player_id].cash >= tile.buy_price


def online_render_game_page(game_id, player_id, dice_result=None):
    game = get_online_game(game_id)
    state = game["state"]

    if player_id not in state.players:
        return redirect(url_for("online_demo_landing"))

    player1 = state.players["player1"]
    player2 = state.players["player2"]
    current_id = current_turn_id(state)

    pending_player = game.get("pending_buy_player_id")
    pending_tile_index = game.get("pending_buy_tile_index")
    has_pending_buy = pending_player is not None

    is_my_turn = (player_id == current_id and not has_pending_buy)
    can_buy_online = online_property_can_be_bought(game, player_id)

    if has_pending_buy:
        if player_id == pending_player:
            online_status_message = "Choose Buy or Skip"
        else:
            online_status_message = f"Waiting for {format_player_name(pending_player)} to choose Buy/Skip"
    elif is_my_turn:
        online_status_message = "Your turn"
    else:
        online_status_message = f"Waiting for {format_player_name(current_id)}"

    viewer = state.players[player_id]
    viewer_tile = config.tiles[viewer.pos]

    property_price = 0
    owner = None

    if pending_tile_index is not None:
        current_tile = config.tiles[pending_tile_index]
    else:
        current_tile = viewer_tile

    if current_tile.tile_type == "property":
        property_price = current_tile.buy_price
        owner_id = state.properties[current_tile.index].owner_id
        owner = format_player_name(owner_id) if owner_id else None

    property_owners = {
        tile_index: property_state.owner_id
        for tile_index, property_state in state.properties.items()
    }

    auto_refresh = (not game["game_over"]) and (not is_my_turn) and (not can_buy_online)

    return render_template(
        "index.html",
        position=player1.pos,
        location=current_tile.name,
        waiting_for_ai=False,
        money=player1.cash,
        ai_money=player2.cash,
        ai_position=player2.pos,
        dice_result=dice_result,
        game_log=game["log"],
        can_buy=can_buy_online,
        property_price=property_price,
        owner=owner,
        game_over=game["game_over"],
        winner=format_player_name(state.winner_id) if state.winner_id else None,
        current_turn=(
            f"{format_player_name(pending_player)} - Buy/Skip" if has_pending_buy
            else format_player_name(current_id)
        ),
        property_owners=property_owners,
        game_id=game_id,
        is_online=True,
        player_id=player_id,
        player_label=format_player_name(player_id),
        other_player_label="Player 2",
        is_my_turn=is_my_turn,
        roll_action=url_for("online_roll", game_id=game_id, player_id=player_id),
        buy_action=url_for("online_buy", game_id=game_id, player_id=player_id),
        skip_buy_action=url_for("online_skip_buy", game_id=game_id, player_id=player_id),
        reset_action=url_for("online_reset", game_id=game_id, player_id=player_id),
        leave_action=url_for("lobby_page"),
        auto_refresh=auto_refresh,
        online_status_message=online_status_message
    )


@app.route("/online-demo")
def online_demo_landing():
    get_online_game("demo")
    return """
    <!doctype html>
    <html lang=\"en\">
    <head>
        <meta charset=\"utf-8\">
        <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
        <title>Temporary Online Multiplayer Demo</title>
        <link href=\"https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css\" rel=\"stylesheet\">
        <style>
            body { min-height: 100vh; display: grid; place-items: center; background: linear-gradient(135deg, #fff8df, #f5d38a); }
            .demo-card { max-width: 740px; width: min(92vw, 740px); border: 0; border-radius: 24px; box-shadow: 0 24px 60px rgba(31,41,51,.2); }
            .btn { border-radius: 999px; font-weight: 800; }
        </style>
    </head>
    <body>
        <div class=\"card demo-card p-4 p-md-5\">
            <a class=\"small text-decoration-none mb-3 d-inline-block\" href=\"/lobby\">← Back to game mode selection</a>
            <h1 class=\"fw-bold mb-3\">🌐 Temporary Online Multiplayer Demo</h1>
            <p class=\"text-muted mb-4\">Use two browser windows to test the same shared game. This mode is ready to connect to the final lobby/user system later.</p>
            <div class=\"d-flex gap-3 flex-wrap\">
                <a class=\"btn btn-danger btn-lg px-4\" href=\"/game/demo/player1\">Join as Player 1</a>
                <a class=\"btn btn-primary btn-lg px-4\" href=\"/game/demo/player2\">Join as Player 2</a>
            </div>
            <hr>
            <p class=\"small text-muted mb-0\">Testing links: /game/demo/player1 and /game/demo/player2</p>
        </div>
    </body>
    </html>
    """


@app.route("/game/<game_id>/<player_id>")
def online_game_page(game_id, player_id):
    return online_render_game_page(game_id, player_id)


@app.route("/game/<game_id>/<player_id>/roll", methods=["POST"])
def online_roll(game_id, player_id):
    game = get_online_game(game_id)
    state = game["state"]

    if game["game_over"]:
        return redirect(url_for("online_game_page", game_id=game_id, player_id=player_id))

    if game.get("pending_buy_player_id") is not None:
        game["log"].append("Please finish the Buy/Skip decision first.")
        return redirect(url_for("online_game_page", game_id=game_id, player_id=player_id))

    if player_id != current_turn_id(state):
        game["log"].append(f"{format_player_name(player_id)} tried to act, but it is not their turn.")
        return redirect(url_for("online_game_page", game_id=game_id, player_id=player_id))

    player = state.players[player_id]
    old_position = player.pos

    acting_player_id = current_turn_id(state)
    event = game["engine"].take_turn(state, online_decision_provider)

    if "player_id" not in event:
        event["player_id"] = acting_player_id

    new_position = player.pos
    game["last_roll"] = (new_position - old_position) % len(config.tiles)

    text = format_event(event)
    if text:
        game["log"].append(text)

    landed_tile = config.tiles[player.pos]
    if landed_tile.tile_type == "property":
        property_state = state.properties[landed_tile.index]
        if property_state.owner_id is None and player.cash >= landed_tile.buy_price:
            game["pending_buy_player_id"] = player_id
            game["pending_buy_tile_index"] = landed_tile.index
            game["log"].append(
                f"{format_player_name(player_id)} may buy {landed_tile.name} for ${landed_tile.buy_price}."
            )

    online_check_game_over(game)

    return redirect(url_for("online_game_page", game_id=game_id, player_id=player_id))


@app.route("/game/<game_id>/<player_id>/buy", methods=["POST"])
def online_buy(game_id, player_id):
    game = get_online_game(game_id)
    state = game["state"]

    if not online_property_can_be_bought(game, player_id):
        game["log"].append(f"{format_player_name(player_id)} cannot buy this property.")
        return redirect(url_for("online_game_page", game_id=game_id, player_id=player_id))

    tile_index = game["pending_buy_tile_index"]
    tile = config.tiles[tile_index]
    player = state.players[player_id]
    property_state = state.properties[tile.index]

    player.cash -= tile.buy_price
    property_state.owner_id = player_id
    game["log"].append(f"{format_player_name(player_id)} bought {tile.name} for ${tile.buy_price}.")

    game["pending_buy_player_id"] = None
    game["pending_buy_tile_index"] = None

    online_check_game_over(game)

    return redirect(url_for("online_game_page", game_id=game_id, player_id=player_id))


@app.route("/game/<game_id>/<player_id>/skip-buy", methods=["POST"])
def online_skip_buy(game_id, player_id):
    game = get_online_game(game_id)

    if game.get("pending_buy_player_id") != player_id:
        game["log"].append(f"{format_player_name(player_id)} cannot skip this purchase decision.")
        return redirect(url_for("online_game_page", game_id=game_id, player_id=player_id))

    tile = config.tiles[game["pending_buy_tile_index"]]
    game["log"].append(f"{format_player_name(player_id)} chose not to buy {tile.name}.")
    game["pending_buy_player_id"] = None
    game["pending_buy_tile_index"] = None

    return redirect(url_for("online_game_page", game_id=game_id, player_id=player_id))


@app.route("/game/<game_id>/<player_id>/reset", methods=["POST"])
def online_reset(game_id, player_id):
    create_online_game(game_id)
    return redirect(url_for("online_game_page", game_id=game_id, player_id=player_id))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
