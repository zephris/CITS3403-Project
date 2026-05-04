from flask import Flask, render_template, redirect, url_for
from template.backend.app.game_logic.engine import load_game_config, GameEngine

app = Flask(__name__)
app.secret_key = "dev-secret-key"

config = load_game_config("template/backend/app/game_logic/data/monopoly_standard.json")
engine = GameEngine(config)

game_state = engine.initialize_game([
    {"player_id": "player1", "name": "Player 1"},
    {"player_id": "ai_1", "name": "AI Player"}
])

game_log = ["Game started! Player 1 is on GO."]


def decision_provider(player_id, action, context):
    if action == "buy_property":
        return {"buy": False}

    if action == "auction_bid":
        return {"bid": False}

    if action == "jail_action":
        return {"choice": "roll"}

    return {}


@app.route("/")
def home():
    player = game_state.players["player1"]
    tile = config.tiles[player.pos]

    return render_template(
        "index.html",
        position=player.pos,
        location=tile.name,
        money=player.cash,
        dice_result=None,
        game_log=game_log
    )


@app.route("/roll")
def roll_dice():

    while game_state.turn_order[game_state.current_turn_index] != "player1":
        ai_event = engine.take_turn(game_state, decision_provider)
        game_log.append(f"AI action: {ai_event.get('type')}")

    event = engine.take_turn(game_state, decision_provider)

    current_player_id = event.get("player_id", "unknown")
    event_type = event.get("type", "unknown")

    if event_type == "property_bought":
        game_log.append(f"{current_player_id} bought {event.get('tile')}.")
    elif event_type == "rent_paid":
        game_log.append(
            f"{event.get('from')} paid ${event.get('amount')} rent to {event.get('to')} for {event.get('tile')}."
        )
    elif event_type == "tax_paid":
        game_log.append(f"{current_player_id} paid ${event.get('amount')} tax.")
    elif event_type == "card_drawn":
        game_log.append(f"{current_player_id} drew a card: {event.get('description')}")
    elif event_type == "landed_own_property":
        game_log.append(f"{current_player_id} landed on their own property: {event.get('tile')}.")
    elif event_type == "auction":
        game_log.append(f"{current_player_id} started an auction for {event.get('tile')}.")
    elif event_type == "no_action":
        game_log.append(f"{current_player_id} landed on {event.get('tile')}.")
    else:
        game_log.append(f"{current_player_id}: {event_type}")

    player = game_state.players["player1"]
    tile = config.tiles[player.pos]

    can_buy = False

    if tile.tile_type == "property":
        property_state = game_state.properties[tile.index]
        if property_state.owner_id is None and player.cash >= tile.buy_price:
            can_buy = True

    return render_template(
        "index.html",
        position=player.pos,
        location=tile.name,
        money=player.cash,
        dice_result="Engine turn completed",
        game_log=game_log,
        can_buy=can_buy,
        property_price=tile.buy_price
    )


@app.route("/reset")
def reset_game():
    global game_state, game_log

    game_state = engine.initialize_game([
        {"player_id": "player1", "name": "Player 1"},
        {"player_id": "ai_1", "name": "AI Player"}
    ])

    game_log = ["Game reset! Player 1 is on GO."]

    return redirect(url_for("home"))

@app.route("/buy")
def buy_property():
    player = game_state.players["player1"]
    tile = config.tiles[player.pos]

    if tile.tile_type == "property":
        property_state = game_state.properties[tile.index]

        if property_state.owner_id is None and player.cash >= tile.buy_price:
            player.cash -= tile.buy_price
            property_state.owner_id = "player1"
            game_log.append(f"Player 1 bought {tile.name} for ${tile.buy_price}.")
        else:
            game_log.append(f"Player 1 cannot buy {tile.name}.")

    return redirect(url_for("home"))

if __name__ == "__main__":
    app.run(debug=True)