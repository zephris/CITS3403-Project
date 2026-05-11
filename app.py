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
        game_id=game_id
    )


@app.route("/")
def home():
    update_buy_status()
    return render_game_page()


@app.route("/roll", methods=["POST"])
def roll_dice():
    global last_roll, can_buy

    if game_over:
        return redirect(url_for("home"))

    can_buy = False

    # Let AI turns finish first
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
                return redirect(url_for("home"))

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

    return redirect(url_for("home"))


@app.route("/buy", methods=["POST"])
def buy_property():
    global can_buy

    if game_over:
        return redirect(url_for("home"))

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
                metadata={
                    "player_id": "player1",
                    "tile": tile.name
                }
            )
        else:
            game_log.append(f"Player 1 cannot buy {tile.name}.")

    can_buy = False

    return redirect(url_for("home"))


@app.route("/skip-buy", methods=["POST"])
def skip_buy():
    global can_buy

    tile = get_current_tile()
    game_log.append(f"Player 1 chose not to buy {tile.name}.")
    can_buy = False

    return redirect(url_for("home"))


@app.route("/reset")
def reset_game():
    global game_state, game_log, last_roll, can_buy, game_over

    game_state = engine.initialize_game(players)
    game_log = ["Game reset! Player 1 is on GO."]
    last_roll = None
    can_buy = False
    game_over = False

    return redirect(url_for("home"))


if __name__ == "__main__":
    app.run(debug=True)