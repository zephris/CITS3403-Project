from flask import Flask, render_template, redirect, url_for, request, session, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from models import db, User, Lobby, LobbyPlayer, LobbyMessage
from template.backend.app.game_logic.engine import load_game_config, GameEngine
import random
import json

app = Flask(__name__)
app.secret_key = "dev-secret-key"

app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///app.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db.init_app(app)

config = load_game_config("template/backend/app/game_logic/data/monopoly_standard.json")
engine = GameEngine(config)

players = [
    {"player_id": "player1", "name": "Player 1"},
    {"player_id": "ai_1", "name": "AI Player"}
]
current_game_players = list(players)

# Temporary local ID for this prototype.
# Later, replace this with the real game_id returned by POST /lobbies/{lobby_id}/start.
game_id = "local_demo_game"

game_state = engine.initialize_game(players)
game_log = [{"type": "system", "message": "Game started! Player 1 is on GO."}]
game_chat_messages = []
last_roll = None
can_buy = False
game_over = False
waiting_for_ai = False

# Multiplayer restart voting state. In LAN multiplayer, a restart only happens
# after every real player has requested it.
restart_votes = set()

# Pending property-purchase state. The game engine advances the turn immediately,
# so we store who landed on an unowned property until they click Buy or Skip.
pending_buy_player_id = None
pending_buy_tile_index = None

# Pending jail decisions submitted from the UI.
# The engine reads these on the jailed player's next turn.
pending_jail_actions = {}
pending_jail_purchases = {}

# Local house tracking for Shuo's enhanced UI.
# Key: tile index, Value: number of houses on that property.
property_houses = {}

# Record how many times each player has landed on each property.
# Key format: "player_id:tile_index"
property_landing_counts = {}

MAX_HOUSES_PER_PROPERTY = 4
HOUSE_COST = 50
HOUSE_RENT_BONUS = 25
HOUSE_SELL_VALUE = 25

# When cash is below this number, the sell-house / sell-property panel appears.
LOW_CASH_SELL_THRESHOLD = HOUSE_COST

# -----------------------------------------------------------------------------
# Per-game runtime storage
# -----------------------------------------------------------------------------
# The original prototype kept these values as one set of module-level globals:
# game_state, game_log, game_chat_messages, property_houses, restart_votes, etc.
# That means two rooms could accidentally share the same board state.  This
# dictionary keeps a separate runtime object for each game_id.  The existing
# helper functions can still use the same variable names because each game route
# activates the correct runtime before handling the request and saves it after.
game_contexts = {}
active_context_game_id = game_id

GAME_RUNTIME_ENDPOINTS = {
    "singleplayer",
    "start_lobby_game_from_lobby",
    "start_lobby_game",
    "game_state_status",
    "game_chat",
    "leave_game_room",
    "game_page",
    "roll_dice",
    "buy_property",
    "skip_buy",
    "ai_turn",
    "jail_pay_fine",
    "jail_use_card",
    "jail_buy_card",
    "build_house",
    "sell_house",
    "sell_property",
    "reset_game",
}




def make_game_log_entry(log_type, message, metadata=None):
    """Create a structured game-log entry for the UI.

    The UI reads `type` to choose icons/colours and `message` to display text.
    `metadata` is optional and can be used later for analytics or filtering.
    """
    if isinstance(message, dict):
        # Already structured. Keep it compatible with old and new callers.
        return {
            "type": message.get("type", log_type or "info"),
            "message": message.get("message", ""),
            "metadata": message.get("metadata", metadata or {}),
        }

    return {
        "type": log_type or "info",
        "message": str(message),
        "metadata": metadata or {},
    }


def append_game_log(log_type, message=None, metadata=None):
    """Append a structured log entry.

    Supports both append_game_log("message") and
    append_game_log("type", "message").
    """
    if message is None:
        message = log_type
        log_type = "info"

    if message:
        game_log.append(make_game_log_entry(log_type, message, metadata))


def get_log_message(log_entry):
    """Return the displayable message from either new dict logs or old strings."""
    if isinstance(log_entry, dict):
        return log_entry.get("message", "")
    return str(log_entry)


def normalize_game_log(log_entries):
    """Convert any legacy string log entries into structured dictionaries."""
    return [
        entry if isinstance(entry, dict) else make_game_log_entry("info", entry)
        for entry in log_entries
    ]


def make_game_context(game_id_value, game_players=None, start_message=None):
    if game_players is None:
        game_players = list(players)

    if start_message is None:
        start_message = f"Game started! {game_players[0]['name']} is on GO."

    return {
        "game_id": game_id_value,
        "game_state": engine.initialize_game(game_players),
        "game_log": [make_game_log_entry("system", start_message)],
        "game_chat_messages": [],
        "last_roll": None,
        "can_buy": False,
        "game_over": False,
        "waiting_for_ai": False,
        "restart_votes": set(),
        "pending_buy_player_id": None,
        "pending_buy_tile_index": None,
        "pending_jail_actions": {},
        "pending_jail_purchases": {},
        "property_houses": {},
        "property_landing_counts": {},
        "current_game_players": list(game_players),
    }


def activate_game_context(game_id_value=None):
    """Load the selected game runtime into the variables used by existing code."""
    global active_context_game_id, game_id, game_state, game_log, game_chat_messages
    global last_roll, can_buy, game_over, waiting_for_ai, restart_votes
    global pending_buy_player_id, pending_buy_tile_index
    global pending_jail_actions, pending_jail_purchases
    global property_houses, property_landing_counts, current_game_players

    if not game_id_value:
        game_id_value = session.get("active_game_id") or game_id or "local_demo_game"

    if game_id_value not in game_contexts:
        game_contexts[game_id_value] = make_game_context(
            game_id_value,
            current_game_players or players,
        )

    context = game_contexts[game_id_value]
    active_context_game_id = game_id_value
    game_id = context["game_id"]
    game_state = context["game_state"]
    game_log = normalize_game_log(context["game_log"])
    game_chat_messages = context["game_chat_messages"]
    last_roll = context["last_roll"]
    can_buy = context["can_buy"]
    game_over = context["game_over"]
    waiting_for_ai = context["waiting_for_ai"]
    restart_votes = context["restart_votes"]
    pending_buy_player_id = context["pending_buy_player_id"]
    pending_buy_tile_index = context["pending_buy_tile_index"]
    pending_jail_actions = context["pending_jail_actions"]
    pending_jail_purchases = context["pending_jail_purchases"]
    property_houses = context["property_houses"]
    property_landing_counts = context["property_landing_counts"]
    current_game_players = context["current_game_players"]

    session["active_game_id"] = game_id_value


def save_active_game_context():
    """Persist the currently active globals back into the per-game dictionary."""
    if not active_context_game_id:
        return

    game_contexts[active_context_game_id] = {
        "game_id": game_id,
        "game_state": game_state,
        "game_log": game_log,
        "game_chat_messages": game_chat_messages,
        "last_roll": last_roll,
        "can_buy": can_buy,
        "game_over": game_over,
        "waiting_for_ai": waiting_for_ai,
        "restart_votes": restart_votes,
        "pending_buy_player_id": pending_buy_player_id,
        "pending_buy_tile_index": pending_buy_tile_index,
        "pending_jail_actions": pending_jail_actions,
        "pending_jail_purchases": pending_jail_purchases,
        "property_houses": property_houses,
        "property_landing_counts": property_landing_counts,
        "current_game_players": current_game_players,
    }


def get_request_game_id():
    if request.view_args and request.view_args.get("game_id"):
        return request.view_args.get("game_id")

    if request.view_args and request.view_args.get("lobby_id") is not None:
        lobby_id = request.view_args.get("lobby_id")
        if request.endpoint == "start_lobby_game_from_lobby":
            return f"lobby_{lobby_id}_game"

    return session.get("active_game_id") or game_id


@app.before_request
def load_game_context_for_request():
    if request.endpoint in GAME_RUNTIME_ENDPOINTS:
        activate_game_context(get_request_game_id())


@app.after_request
def save_game_context_after_request(response):
    if request.endpoint in GAME_RUNTIME_ENDPOINTS:
        save_active_game_context()
    return response

game_contexts[game_id] = make_game_context(game_id, current_game_players, get_log_message(game_log[0]))

lobby_demo_state = {
    "player2_ready": False,
    "messages": [
        {"sender": "System", "text": "Welcome to the lobby."},
        {"sender": "System", "text": "Waiting for more players to join."},
        {"sender": "Player 2", "text": "Ready when you are."}
    ]
}
lobby_browser_state = {
    "lobbies": [
        {
            "id": 1,
            "name": "Perth Room 1",
            "host": "Player 1",
            "players": 2,
            "max_players": 4,
            "status": "Waiting"
        },
        {
            "id": 2,
            "name": "WA Monopoly Fans",
            "host": "Anthony",
            "players": 4,
            "max_players": 4,
            "status": "Full"
        },
        {
            "id": 3,
            "name": "City Match",
            "host": "Shuo",
            "players": 1,
            "max_players": 4,
            "status": "Waiting"
        },
        {
            "id": 4,
            "name": "Late Night Game",
            "host": "Dazai",
            "players": 3,
            "max_players": 4,
            "status": "Starting Soon"
        }
    ],
    "next_lobby_id": 5
}
def decision_provider(player_id, action, context):
    if action == "buy_property":
        if player_id.startswith("ai"):
            return {"buy": random.choice([True, False])}

        return {"buy": False}

    if action == "auction_bid":
        return {"bid": False}

    if action == "jail_action":
        # Human players can choose from the jail panel. If they simply press
        # Roll Dice, the default remains trying to roll doubles.
        selected = pending_jail_actions.pop(player_id, None)
        if selected is None:
            return {"choice": "roll"}

        if selected.get("choice") == "buy_card":
            pending_jail_purchases[player_id] = selected

        return selected

    if action == "jail_buy_offer":
        purchase = pending_jail_purchases.get(player_id, {})
        sellers = context.get("sellers", [])
        seller_id = purchase.get("seller_id") or context.get("seller_id")
        if seller_id not in sellers and sellers:
            seller_id = sellers[0]
        return {
            "seller_id": seller_id,
            "offer": int(purchase.get("offer", config.jail_fine)),
        }

    if action == "jail_buy_response":
        # Prototype LAN implementation: a seller with a card accepts the offer.
        seller = game_state.players.get(player_id)
        return {"accept": bool(seller and seller.jail_cards > 0 and context.get("offer", 0) > 0)}

    return {}


def get_player():
    return get_visible_player()


def get_current_tile():
    return get_visible_tile()


def format_player_name(player_id):
    if not player_id:
        return "System"

    player = game_state.players.get(player_id)
    if player is not None:
        return player.name

    if player_id == "player1":
        return "Player 1"
    if player_id == "player2":
        return "Player 2"
    if player_id.startswith("ai"):
        return "AI Player"
    return "System"


def is_singleplayer_mode():
    return not str(game_id).startswith("lobby_")


def get_current_user_player_id():
    """
    In singleplayer, the browser user is always player1 and ai_1 is the computer.
    In LAN multiplayer, the logged-in username is mapped to the matching game player.
    """
    if is_singleplayer_mode():
        return "player1"

    username = session.get("username")
    if username:
        for player_id, player in game_state.players.items():
            if player.name == username:
                return player_id

    return game_state.turn_order[0] if game_state.turn_order else "player1"


def get_other_player_id():
    current_user_player_id = get_current_user_player_id()

    for player_id in game_state.turn_order:
        if player_id != current_user_player_id:
            return player_id

    return current_user_player_id


def get_visible_player():
    player_id = get_current_user_player_id()
    return game_state.players.get(player_id) or game_state.players[game_state.turn_order[0]]


def get_visible_tile():
    return config.tiles[get_visible_player().pos]




def get_active_player():
    return game_state.players[get_active_player_id()]


def get_active_tile():
    return config.tiles[get_active_player().pos]


def get_pending_buy_tile():
    if pending_buy_tile_index is None:
        return None
    return config.tiles[pending_buy_tile_index]


def current_user_can_act():
    current_user_player_id = get_current_user_player_id()

    if can_buy:
        return pending_buy_player_id == current_user_player_id

    return get_active_player_id() == current_user_player_id


def maybe_create_pending_buy(acting_player_id):
    """
    The engine currently resolves an unowned-property landing by asking
    decision_provider(), then advances the turn. For the UI we still want
    the human player to be able to choose Buy or Skip, so we detect the
    landed tile and keep a pending decision.
    """
    global can_buy, pending_buy_player_id, pending_buy_tile_index

    player = game_state.players[acting_player_id]
    tile = config.tiles[player.pos]

    can_buy = False
    pending_buy_player_id = None
    pending_buy_tile_index = None

    if tile.tile_type != "property":
        return

    property_state = game_state.properties[tile.index]
    if property_state.owner_id is None and player.cash >= tile.buy_price:
        can_buy = True
        pending_buy_player_id = acting_player_id
        pending_buy_tile_index = tile.index


def clear_pending_buy():
    global can_buy, pending_buy_player_id, pending_buy_tile_index
    can_buy = False
    pending_buy_player_id = None
    pending_buy_tile_index = None


def format_event(event):
    event_type = event.get("type", "unknown")
    player_id = event.get("player_id") or event.get("from") or event.get("to")
    name = format_player_name(player_id)

    if event_type == "property_bought":
        return f"{name} bought {event.get('tile')}."

    if event_type == "rent_paid":
        text = (
            f"{format_player_name(event.get('from'))} paid "
            f"${event.get('amount')} rent to "
            f"{format_player_name(event.get('to'))} for {event.get('tile')}."
        )
        if event.get("bankrupt"):
            text += f" {format_player_name(event.get('from'))} is bankrupt and exits the game."
        return text

    if event_type == "tax_paid":
        text = f"{name} paid ${event.get('amount')} tax."
        if event.get("bankrupt"):
            text += f" {name} is bankrupt and exits the game."
        return text

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

    if event_type == "go_to_jail":
        return f"{name} landed on Go To Jail and was sent to Jail."

    if event_type == "jail_paid_fine":
        return f"{name} paid ${event.get('fine')} and left jail."

    if event_type == "jail_bought_card":
        negotiation = event.get("negotiation", {})
        return (
            f"{name} bought a Get Out of Jail Free card from "
            f"{format_player_name(negotiation.get('seller_id'))} for ${negotiation.get('price')}."
        )

    if event_type == "jail_buy_failed":
        return f"{name} could not buy a Get Out of Jail Free card and remains in jail."

    if event_type == "jail_release":
        jail_text = format_event(event.get("jail_event", {}))
        tile_text = format_event(event.get("tile_event", {}))
        return f"{jail_text} Then {tile_text}"

    if event_type == "go_to_jail_double":
        return f"{name} rolled doubles three times and went to jail."

    if event_type == "jail_roll_failed":
        return f"{name} failed to roll doubles and remains in jail."

    if event_type == "jail_roll_doubles":
        return f"{name} rolled doubles and got out of jail."

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
    """Temporary local finalize function for both 2-, 3-, and 4-player games."""
    active_players = [
        player_id for player_id in game_state.turn_order
        if not getattr(game_state.players[player_id], "bankrupt", False)
    ]

    player_results = []
    for player_id in game_state.turn_order:
        player = game_state.players[player_id]
        player_results.append({
            "user_id": player_id,
            "final_rank": 1 if player_id == game_state.winner_id else (2 if player_id not in active_players else 1),
            "bankrupt_flag": getattr(player, "bankrupt", False),
            "turns_taken": getattr(player, "turns_taken", 0),
            "cash": player.cash,
        })

    result = {
        "game_id": game_id,
        "winner_user_id": game_state.winner_id,
        "player_results": player_results,
    }

    print(result)

def update_buy_status():
    """
    can_buy is now controlled by pending_buy_player_id/pending_buy_tile_index.
    If there is no pending buy choice, can_buy must stay False.
    """
    global can_buy

    if pending_buy_player_id is None or pending_buy_tile_index is None:
        can_buy = False
        return

    player = game_state.players.get(pending_buy_player_id)
    tile = config.tiles[pending_buy_tile_index]
    property_state = game_state.properties.get(pending_buy_tile_index)

    can_buy = (
        player is not None
        and property_state is not None
        and property_state.owner_id is None
        and player.cash >= tile.buy_price
    )


def check_game_over():
    global game_over

    if game_state.winner_id and not game_over:
        game_over = True
        append_game_log("game_over", f"Game over! Winner: {format_player_name(game_state.winner_id)}")
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
            append_game_log(ai_event.get("type", "ai_turn"), text)

        check_game_over()
        safety_counter += 1



def is_ajax_request():
    return request.headers.get("X-Requested-With") == "XMLHttpRequest"


def current_game_mode():
    return "singleplayer" if is_singleplayer_mode() else "multiplayer"

def get_lobby_id_from_game_id(game_id_value):
    game_id_text = str(game_id_value)

    if not game_id_text.startswith("lobby_") or not game_id_text.endswith("_game"):
        return None

    lobby_id_text = game_id_text.replace("lobby_", "").replace("_game", "")

    try:
        return int(lobby_id_text)
    except ValueError:
        return None


def get_lobby_from_game_id(game_id_value):
    lobby_id = get_lobby_id_from_game_id(game_id_value)

    if lobby_id is None:
        return None

    return db.session.get(Lobby, lobby_id)


def get_restart_required_count():
    if current_game_mode() == "multiplayer":
        return len(game_state.turn_order)
    return 1


def get_restart_vote_names():
    return [format_player_name(player_id) for player_id in sorted(restart_votes)]


def get_active_player_id():
    return game_state.turn_order[game_state.current_turn_index]

def make_property_landing_key(player_id, tile_index):
    return f"{player_id}:{tile_index}"


def record_property_landing(player_id, tile_index):
    key = make_property_landing_key(player_id, tile_index)
    property_landing_counts[key] = property_landing_counts.get(key, 0) + 1


def get_property_landing_count(player_id, tile_index):
    key = make_property_landing_key(player_id, tile_index)
    return property_landing_counts.get(key, 0)


def player_needs_cash(player_id):
    player = game_state.players.get(player_id)
    if player is None:
        return False

    return player.cash < LOW_CASH_SELL_THRESHOLD


def perform_ai_property_management(ai_player_id):
    """
    AI randomly builds houses and sells houses/properties.
    This never shows a UI panel because it is handled fully by backend logic.
    """
    if not ai_player_id.startswith("ai"):
        return

    player = game_state.players.get(ai_player_id)
    if player is None or player.bankrupt:
        return

    owned_properties = [
        tile_index
        for tile_index, property_state in game_state.properties.items()
        if property_state.owner_id == ai_player_id
    ]

    if not owned_properties:
        return

    # If AI has low cash, randomly sell one house first.
    if player_needs_cash(ai_player_id):
        house_properties = [
            tile_index
            for tile_index in owned_properties
            if game_state.properties[tile_index].houses > 0
            or property_houses.get(tile_index, 0) > 0
        ]

        if house_properties and random.choice([True, False]):
            tile_index = random.choice(house_properties)
            property_state = game_state.properties[tile_index]
            current_houses = property_state.houses or property_houses.get(tile_index, 0)

            property_state.houses = max(0, current_houses - 1)

            if property_state.houses > 0:
                property_houses[tile_index] = property_state.houses
            else:
                property_houses.pop(tile_index, None)

            player.cash += HOUSE_SELL_VALUE
            append_game_log(
                "house_sold",
                f"{format_player_name(ai_player_id)} sold one house on "
                f"{config.tiles[tile_index].name} for ${HOUSE_SELL_VALUE}."
            )
            return

        # If there is no house to sell, AI may sell one property.
        if owned_properties:
            tile_index = random.choice(owned_properties)
            tile = config.tiles[tile_index]
            property_state = game_state.properties[tile_index]
            house_count = property_state.houses or property_houses.get(tile_index, 0)
            sell_value = (tile.buy_price // 2) + (house_count * HOUSE_SELL_VALUE)

            player.cash += sell_value
            property_state.owner_id = None
            property_state.houses = 0
            property_state.has_hotel = False
            property_state.mortgaged = False
            property_houses.pop(tile_index, None)

            append_game_log(
                "property_sold",
                f"{format_player_name(ai_player_id)} sold {tile.name} for ${sell_value}."
            )
            return

    # If AI has enough money, it may randomly build a house.
    buildable_properties = []
    for tile_index in owned_properties:
        property_state = game_state.properties[tile_index]
        house_count = property_state.houses or property_houses.get(tile_index, 0)
        landing_count = get_property_landing_count(ai_player_id, tile_index)

        if (
            landing_count >= 2
            and house_count < MAX_HOUSES_PER_PROPERTY
            and player.cash >= HOUSE_COST
        ):
            buildable_properties.append(tile_index)

    if buildable_properties and random.choice([True, False]):
        tile_index = random.choice(buildable_properties)
        property_state = game_state.properties[tile_index]
        house_count = property_state.houses or property_houses.get(tile_index, 0)

        player.cash -= HOUSE_COST
        property_state.houses = house_count + 1
        property_houses[tile_index] = property_state.houses

        append_game_log(
            "house_built",
            f"{format_player_name(ai_player_id)} built a house on "
            f"{config.tiles[tile_index].name}."
        )


def get_active_property_info():
    """
    Build the data used by the property-management panel.

    New rules:
    - A player can build a house only after landing on their owned property
      for the second time or later.
    - Selling houses/properties is only available when the player has low cash.
    - AI property management is handled automatically in backend logic.
    """
    tile = get_visible_tile()
    current_user_player_id = get_current_user_player_id()
    player = game_state.players[current_user_player_id]

    info = {
        "house_count": 0,
        "can_build_house": False,
        "can_sell_house": False,
        "can_sell_property": False,
        "buildable_house_properties": [],
        "sellable_house_properties": [],
        "sellable_properties": [],
        "active_property_player_name": format_player_name(current_user_player_id),
        "needs_cash": player_needs_cash(current_user_player_id),
    }

    if tile.tile_type == "property":
        property_state = game_state.properties[tile.index]
        synced_houses = property_state.houses or property_houses.get(tile.index, 0)
        property_state.houses = synced_houses

        if synced_houses > 0:
            property_houses[tile.index] = synced_houses
        else:
            property_houses.pop(tile.index, None)

        info["house_count"] = synced_houses

    management_allowed = (
        not waiting_for_ai
        and not game_over
        and not can_buy
        and current_user_can_act()
    )

    # Build house:
    # Only on the property the player is currently standing on,
    # only if the player owns it,
    # only after the second landing.
    if tile.tile_type == "property":
        property_state = game_state.properties[tile.index]
        house_count = property_state.houses or property_houses.get(tile.index, 0)
        landing_count = get_property_landing_count(current_user_player_id, tile.index)

        if (
            management_allowed
            and property_state.owner_id == current_user_player_id
            and landing_count >= 2
            and house_count < MAX_HOUSES_PER_PROPERTY
            and player.cash >= HOUSE_COST
        ):
            info["buildable_house_properties"].append({
                "tile_index": tile.index,
                "name": tile.name,
                "houses": house_count,
                "next_houses": house_count + 1,
                "cost": HOUSE_COST,
                "landing_count": landing_count,
            })

    # Sell house / property:
    # Only when the player needs cash.
    if management_allowed and player_needs_cash(current_user_player_id):
        for tile_index, property_state in game_state.properties.items():
            if property_state.owner_id != current_user_player_id:
                continue

            tile_obj = config.tiles[tile_index]
            house_count = property_state.houses or property_houses.get(tile_index, 0)
            property_state.houses = house_count

            if house_count > 0:
                property_houses[tile_index] = house_count
                info["sellable_house_properties"].append({
                    "tile_index": tile_index,
                    "name": tile_obj.name,
                    "houses": house_count,
                    "sell_value": HOUSE_SELL_VALUE,
                })
            else:
                property_houses.pop(tile_index, None)

            info["sellable_properties"].append({
                "tile_index": tile_index,
                "name": tile_obj.name,
                "houses": house_count,
                "sell_value": (tile_obj.buy_price // 2) + (house_count * HOUSE_SELL_VALUE),
            })

    info["can_build_house"] = len(info["buildable_house_properties"]) > 0
    info["can_sell_house"] = len(info["sellable_house_properties"]) > 0
    info["can_sell_property"] = len(info["sellable_properties"]) > 0

    return info

def get_all_player_view_models():
    token_icons = ["🧍", "🚗", "🎩", "🐶"]
    current_user_player_id = get_current_user_player_id()
    active_player_id = get_active_player_id()

    result = []
    for index, player_id in enumerate(game_state.turn_order):
        player = game_state.players[player_id]
        result.append({
            "player_id": player_id,
            "name": player.name,
            "cash": player.cash,
            "pos": player.pos,
            "bankrupt": bool(getattr(player, "bankrupt", False)),
            "in_jail_turns": getattr(player, "in_jail_turns", 0),
            "jail_cards": getattr(player, "jail_cards", 0),
            "is_you": player_id == current_user_player_id,
            "is_current_turn": player_id == active_player_id,
            "token": token_icons[index % len(token_icons)],
        })

    return result


def get_jail_action_info():
    current_user_player_id = get_current_user_player_id()
    active_player_id = get_active_player_id()
    player = game_state.players.get(current_user_player_id)

    can_choose = (
        not game_over
        and not waiting_for_ai
        and not can_buy
        and current_user_player_id == active_player_id
        and player is not None
        and player.in_jail_turns > 0
        and not player.bankrupt
    )

    sellers = []
    if can_choose:
        for other_id, other in game_state.players.items():
            if other_id != current_user_player_id and other.jail_cards > 0 and not other.bankrupt:
                sellers.append({
                    "player_id": other_id,
                    "name": other.name,
                    "cards": other.jail_cards,
                })

    return {
        "can_choose_jail_action": can_choose,
        "jail_turns": player.in_jail_turns if player else 0,
        "jail_cards": player.jail_cards if player else 0,
        "jail_fine": config.jail_fine,
        "jail_card_sellers": sellers,
    }


def process_active_turn(dice_result_for_response=False):
    global last_roll, waiting_for_ai

    clear_pending_buy()

    acting_player_id = get_active_player_id()
    old_position = game_state.players[acting_player_id].pos
    event = engine.take_turn(game_state, decision_provider)

    if "player_id" not in event:
        event["player_id"] = acting_player_id

    new_position = game_state.players[acting_player_id].pos
    if event.get("roll") is not None:
        last_roll = event.get("roll")
    else:
        last_roll = (new_position - old_position) % len(config.tiles)
    landed_tile = config.tiles[new_position]
    if landed_tile.tile_type == "property":
        record_property_landing(acting_player_id, landed_tile.index)

    text = format_event(event)
    if text:
        append_game_log(event.get("type", "info"), text)

    maybe_create_pending_buy(acting_player_id)
    check_game_over()

    if not game_over and not can_buy and is_singleplayer_mode() and get_active_player_id() != "player1":
        waiting_for_ai = True
    else:
        waiting_for_ai = False

    return last_roll if dice_result_for_response else None


def build_game_template_context(dice_result=None):
    player = get_visible_player()
    tile = get_visible_tile()

    current_user_player_id = get_current_user_player_id()
    second_player_id = get_other_player_id()
    second_player = game_state.players.get(second_player_id, player)
    all_players = get_all_player_view_models()
    jail_info = get_jail_action_info()

    active_tile = get_pending_buy_tile() or get_active_tile()
    property_price = 0
    owner = None

    if active_tile.tile_type == "property":
        property_price = active_tile.buy_price
        owner_id = game_state.properties[active_tile.index].owner_id
        owner = format_player_name(owner_id) if owner_id else None

    property_owners = {}
    for tile_index, property_state in game_state.properties.items():
        property_owners[tile_index] = property_state.owner_id

    active_info = get_active_property_info()
    active_player_id = get_active_player_id()
    is_current_user_turn = current_user_can_act()

    return {
        "position": player.pos,
        "location": tile.name,
        "waiting_for_ai": waiting_for_ai,
        "money": player.cash,
        "ai_money": second_player.cash,
        "ai_position": second_player.pos,
        "all_players": all_players,
        "all_players_json": json.dumps(all_players),
        "dice_result": dice_result,
        "game_log": game_log,
        "game_chat_messages": game_chat_messages,
        "can_buy": can_buy and pending_buy_player_id == current_user_player_id,
        "property_price": property_price,
        "owner": owner,
        "game_over": game_over,
        "winner": format_player_name(game_state.winner_id) if game_state.winner_id else None,
        "current_turn": format_player_name(active_player_id),
        "property_owners": property_owners,
        "game_id": game_id,

        "game_mode": current_game_mode(),
        "is_current_user_turn": is_current_user_turn,
        "can_control_current_action": is_current_user_turn,
        "current_player_name": format_player_name(current_user_player_id),
        "second_player_icon": "🤖" if current_game_mode() == "singleplayer" else "👥",
        "second_player_name": format_player_name(second_player_id),
        "property_houses_json": json.dumps(property_houses),
        "house_count": active_info["house_count"],
        "max_houses": MAX_HOUSES_PER_PROPERTY,
        "house_cost": HOUSE_COST,
        "house_rent_bonus": HOUSE_RENT_BONUS,
        "house_sell_value": HOUSE_SELL_VALUE,
        "can_build_house": active_info["can_build_house"],
        "can_sell_house": active_info["can_sell_house"],
        "buildable_house_properties": active_info["buildable_house_properties"],
        "sellable_house_properties": active_info["sellable_house_properties"],
        "sellable_properties": active_info["sellable_properties"],
        "can_sell_property": active_info["can_sell_property"],
        "active_property_player_name": active_info["active_property_player_name"],
        "needs_cash": active_info["needs_cash"],

        # Multiplayer restart voting.
        "restart_votes_count": len(restart_votes),
        "restart_required_count": get_restart_required_count(),
        "restart_has_voted": current_user_player_id in restart_votes,
        "restart_vote_names": get_restart_vote_names(),
        **jail_info,
    }


def render_game_html(dice_result=None):
    return render_template("index.html", **build_game_template_context(dice_result))


def make_dice_pair_from_total(total):
    try:
        total = int(total)
    except (TypeError, ValueError):
        total = 2

    if total < 2:
        return 1, 1
    if total > 12:
        return 6, 6

    first = max(1, min(6, total - 1))
    second = total - first

    if second < 1:
        second = 1
        first = total - second

    if second > 6:
        second = 6
        first = total - second

    return first, second


def ajax_dice_response(dice_result=None):
    dice_one, dice_two = make_dice_pair_from_total(dice_result or last_roll or 2)
    return jsonify({
        "ok": True,
        "dice_one": dice_one,
        "dice_two": dice_two,
        "dice_result": dice_result or last_roll or (dice_one + dice_two),
        "html": render_game_html(),
    })


def render_game_page(dice_result=None):
    return render_game_html(dice_result)


@app.route("/")
def home():
    return render_template(
        "home.html",
        username=session.get("username")
    )

@app.route("/singleplayer")
def singleplayer():
    global game_state, game_log, game_chat_messages, last_roll, can_buy, game_over, waiting_for_ai, game_id
    global property_houses, property_landing_counts, current_game_players, restart_votes, active_context_game_id

    game_id = "local_demo_game"
    active_context_game_id = game_id
    session["active_game_id"] = game_id
    current_game_players = [
        {"player_id": "player1", "name": session.get("username", "Player 1")},
        {"player_id": "ai_1", "name": "AI Player"},
    ]
    game_state = engine.initialize_game(current_game_players)
    game_log = [make_game_log_entry("system", "Singleplayer game started! Player 1 is on GO.")]
    game_chat_messages = []
    last_roll = None
    clear_pending_buy()
    pending_jail_actions.clear()
    pending_jail_purchases.clear()
    game_over = False
    waiting_for_ai = False
    property_houses = {}
    property_landing_counts = {}
    restart_votes = set()

    return redirect(url_for("game_page", game_id=game_id))


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()

        if not username or not password:
            return render_template(
                "register.html",
                error="Username and password are required."
            )

        existing_user = User.query.filter_by(username=username).first()

        if existing_user:
            return render_template(
                "register.html",
                error="Username already exists."
            )

        new_user = User(
            username=username,
            password_hash=generate_password_hash(password)
        )

        db.session.add(new_user)
        db.session.commit()

        session["user_id"] = new_user.id
        session["username"] = new_user.username

        return redirect(url_for("home"))

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()

        user = User.query.filter_by(username=username).first()

        if user is None or not check_password_hash(user.password_hash, password):
            return render_template(
                "login.html",
                error="Invalid username or password."
            )

        session["user_id"] = user.id
        session["username"] = user.username

        return redirect(url_for("home"))

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))


@app.route("/profile", methods=["GET", "POST"])
def profile():
    if "username" not in session:
        return redirect(url_for("login"))

    username = session["username"]

    user = User.query.filter_by(username=username).first()

    if user is None:
        session.clear()
        return redirect(url_for("login"))

    back_url = request.args.get("next") or url_for("home")
    back_label = "Back to Lobby" if back_url.startswith("/lobby/") else "Home"

    if request.method == "POST":
        bio = request.form.get("bio", "").strip()
        profile_public = request.form.get("profile_public") == "on"

        if not bio:
            bio = "Monopoly Perth player"

        user.bio = bio[:300]
        user.profile_public = profile_public
        db.session.commit()

        return redirect(url_for("profile", next=back_url))

    joined_lobby_players = (
        LobbyPlayer.query
        .filter_by(player_name=username)
        .order_by(LobbyPlayer.joined_at.desc())
        .all()
    )

    joined_lobbies = [
        lobby_player.lobby
        for lobby_player in joined_lobby_players
        if lobby_player.lobby is not None
    ]

    total_lobbies = len(joined_lobbies)

    hosted_count = LobbyPlayer.query.filter_by(
        player_name=username,
        is_host=True
    ).count()

    games_won = 0
    win_rate = 0

    return render_template(
        "profile.html",
        user=user,
        username=username,
        total_lobbies=total_lobbies,
        hosted_count=hosted_count,
        games_won=games_won,
        win_rate=win_rate,
        joined_lobbies=joined_lobbies,
        back_url=back_url,
        back_label=back_label
    )


@app.route("/users/<username>")
def public_profile(username):
    target_user = User.query.filter_by(username=username).first()

    back_url = request.args.get("next") or url_for("lobby_browser")
    back_label = "Back to Lobby" if back_url.startswith("/lobby/") else "Lobby Browser"

    if target_user is None:
        return render_template(
            "simple_page.html",
            title="User Not Found",
            message="This user profile does not exist."
        )

    if session.get("username") == username:
        return redirect(url_for("profile", next=back_url))

    bio = getattr(target_user, "bio", "Monopoly Perth player")
    profile_public = getattr(target_user, "profile_public", True)

    if not profile_public:
        return render_template(
            "simple_page.html",
            title="Private Profile",
            message="This user's profile is private."
        )

    joined_lobby_players = (
        LobbyPlayer.query
        .filter_by(player_name=username)
        .order_by(LobbyPlayer.joined_at.desc())
        .all()
    )

    joined_lobbies = [
        lobby_player.lobby
        for lobby_player in joined_lobby_players
        if lobby_player.lobby is not None
    ]

    total_lobbies = len(joined_lobbies)

    hosted_count = LobbyPlayer.query.filter_by(
        player_name=username,
        is_host=True
    ).count()

    return render_template(
        "public_profile.html",
        viewed_user=target_user,
        viewed_username=username,
        bio=bio,
        total_lobbies=total_lobbies,
        hosted_count=hosted_count,
        joined_lobbies=joined_lobbies,
        back_url=back_url,
        back_label=back_label
    )

@app.route("/settings")
def settings():
    return render_template(
        "simple_page.html",
        title="Settings",
        message="Settings page is not implemented yet."
    )


@app.route("/credit")
def credit():
    return render_template(
        "simple_page.html",
        title="Credits",
        message="Monopoly Web - Perth Edition project."
    )


@app.route("/browser")
def lobby_browser():
    search_text = request.args.get("search", "").strip()
    quick_join_error = request.args.get("quick_join_error")
    create_lobby_error = request.args.get("create_lobby_error")

    query = Lobby.query.filter(Lobby.status != "in_game")

    if search_text:
        query = query.filter(
            db.or_(
                Lobby.name.ilike(f"%{search_text}%"),
                Lobby.host_name.ilike(f"%{search_text}%")
            )
        )

    lobbies = query.order_by(Lobby.created_at.desc()).all()

    open_rooms = Lobby.query.filter(Lobby.status == "waiting").count()

    return render_template(
        "lobby_browser.html",
        lobbies=lobbies,
        search_text=search_text,
        quick_join_error=quick_join_error,
        create_lobby_error=create_lobby_error,
        online_players=12,
        open_rooms=open_rooms
    )

@app.route("/browser/create", methods=["POST"])
def create_browser_lobby():
    if "username" not in session:
        return redirect(url_for("login"))

    username = session["username"]

    lobby_name = request.form.get("lobby_name", "").strip()
    lobby_type = request.form.get("lobby_type", "public")
    max_players = int(request.form.get("max_players", 4))

    if not lobby_name:
        lobby_name = f"{username}'s Lobby"

    existing_lobby = Lobby.query.filter(
        db.func.lower(Lobby.name) == lobby_name.lower(),
        Lobby.status != "in_game"
    ).first()

    if existing_lobby is not None:
        return redirect(url_for(
            "lobby_browser",
            create_lobby_error=f'Room name "{lobby_name}" is already taken. Please choose another name.'
        ))

    if lobby_type not in ["public", "private"]:
        lobby_type = "public"

    max_players = max(2, min(max_players, 4))

    new_lobby = Lobby(
        name=lobby_name,
        lobby_type=lobby_type,
        host_name=username,
        max_players=max_players,
        invite_code=Lobby.generate_invite_code(),
        status="waiting",
    )

    db.session.add(new_lobby)
    db.session.commit()

    host_player = LobbyPlayer(
        lobby_id=new_lobby.id,
        player_name=username,
        is_host=True,
        is_ready=True
    )

    welcome_message = LobbyMessage(
        lobby_id=new_lobby.id,
        sender_name="System",
        message_text=f"{username} created the lobby."
    )

    db.session.add(host_player)
    db.session.add(welcome_message)
    db.session.commit()

    return redirect(url_for("lobby_page", lobby_id=new_lobby.id))


@app.route("/browser/join/<int:lobby_id>", methods=["POST"])
def join_browser_lobby(lobby_id):
    if "username" not in session:
        return redirect(url_for("login"))

    username = session["username"]

    lobby = db.session.get(Lobby, lobby_id)

    if lobby is None:
        return redirect(url_for("lobby_browser"))

    if lobby.status == "in_game":
        return redirect(url_for("lobby_browser"))

    existing_player = LobbyPlayer.query.filter_by(
        lobby_id=lobby.id,
        player_name=username
    ).first()

    if existing_player is not None:
        return redirect(url_for("lobby_page", lobby_id=lobby.id))

    if len(lobby.players) >= lobby.max_players:
        return redirect(url_for("lobby_browser"))

    player = LobbyPlayer(
        lobby_id=lobby.id,
        player_name=username,
        is_host=False,
        is_ready=False
    )

    db.session.add(player)
    db.session.commit()

    return redirect(url_for("lobby_page", lobby_id=lobby.id))


@app.route("/browser/quick-join", methods=["POST"])
def quick_join_lobby():
    if "username" not in session:
        return redirect(url_for("login"))

    username = session["username"]

    lobbies = (
        Lobby.query
        .filter_by(status="waiting")
        .order_by(Lobby.created_at.asc())
        .all()
    )

    available_lobbies = []

    for lobby in lobbies:
        existing_player = LobbyPlayer.query.filter_by(
            lobby_id=lobby.id,
            player_name=username
        ).first()

        if existing_player is not None:
            return redirect(url_for("lobby_page", lobby_id=lobby.id))

        if len(lobby.players) < lobby.max_players:
            available_lobbies.append(lobby)

    if not available_lobbies:
        return redirect(url_for(
            "lobby_browser",
            quick_join_error="No available lobby was found. Please create a lobby or wait for another room to open."
        ))

    selected_lobby = random.choice(available_lobbies)

    player = LobbyPlayer(
        lobby_id=selected_lobby.id,
        player_name=username,
        is_host=False,
        is_ready=False
    )

    message = LobbyMessage(
        lobby_id=selected_lobby.id,
        sender_name="System",
        message_text=f"{username} joined the lobby using Quick Join."
    )

    db.session.add(player)
    db.session.add(message)
    db.session.commit()

    return redirect(url_for("lobby_page", lobby_id=selected_lobby.id))

@app.route("/lobby/<int:lobby_id>")
def lobby_page(lobby_id):
    if "username" not in session:
        return redirect(url_for("login"))

    username = session["username"]

    lobby = db.session.get(Lobby, lobby_id)

    if lobby is None:
        return redirect(url_for("lobby_browser"))

    players = (
        LobbyPlayer.query.filter_by(lobby_id=lobby.id)
        .order_by(LobbyPlayer.joined_at.asc())
        .all()
    )

    messages = (
        LobbyMessage.query.filter_by(lobby_id=lobby.id)
        .order_by(LobbyMessage.created_at.asc())
        .all()
    )

    current_player = LobbyPlayer.query.filter_by(
        lobby_id=lobby.id,
        player_name=username
    ).first()

    if current_player is None:
        return redirect(url_for("lobby_browser"))

    is_host = current_player.is_host
    player_count = len(players)
    non_host_players = [
        player for player in players
        if not player.is_host
    ]

    lobby_is_full = player_count == lobby.max_players
    non_host_players_ready = all(
        player.is_ready for player in non_host_players
    )

    can_start_game = (
        is_host
        and lobby_is_full
        and non_host_players_ready
    )

    if player_count < lobby.max_players:
        lobby_status = f"Waiting for players... {player_count} / {lobby.max_players}"
    elif not non_host_players_ready:
        lobby_status = "Waiting for all players to ready up..."
    else:
        lobby_status = "Ready to start."

    start_error = request.args.get("start_error")

    return render_template(
        "waiting_lobby.html",
        lobby=lobby,
        players=players,
        messages=messages,
        current_player=current_player,
        is_host=is_host,
        can_start_game=can_start_game,
        player_count=player_count,
        lobby_status=lobby_status,
        start_error=start_error
    )

@app.route("/lobby/<int:lobby_id>/status")
def lobby_status(lobby_id):
    lobby = db.session.get(Lobby, lobby_id)

    if lobby is None:
        return jsonify({
            "exists": False,
            "status": "not_found",
            "game_url": None,
            "redirect_url": url_for("lobby_browser")
        })

    game_url = None

    if lobby.status == "in_game":
        game_url = url_for("game_page", game_id=f"lobby_{lobby.id}_game")

    return jsonify({
        "exists": True,
        "status": lobby.status,
        "game_url": game_url,
        "redirect_url": None
    })

@app.route("/lobby/<int:lobby_id>/ready", methods=["POST"])
def toggle_lobby_ready(lobby_id):
    if "username" not in session:
        return redirect(url_for("login"))

    username = session["username"]

    player = LobbyPlayer.query.filter_by(
        lobby_id=lobby_id,
        player_name=username
    ).first()

    if player is None:
        return redirect(url_for("lobby_browser"))

    if player.is_host:
        return redirect(url_for("lobby_page", lobby_id=lobby_id))

    player.is_ready = not player.is_ready
    db.session.commit()

    return redirect(url_for("lobby_page", lobby_id=lobby_id))


@app.route("/lobby/<int:lobby_id>/leave", methods=["POST"])
def leave_lobby(lobby_id):
    if "username" not in session:
        return redirect(url_for("login"))

    username = session["username"]

    lobby = db.session.get(Lobby, lobby_id)

    if lobby is None:
        return redirect(url_for("lobby_browser"))

    player = LobbyPlayer.query.filter_by(
        lobby_id=lobby_id,
        player_name=username
    ).first()

    if player is None:
        return redirect(url_for("lobby_browser"))

    if player.is_host:
        db.session.delete(lobby)
        db.session.commit()
        return redirect(url_for("lobby_browser"))

    db.session.delete(player)

    remaining_players = LobbyPlayer.query.filter_by(
        lobby_id=lobby.id
    ).all()

    for remaining_player in remaining_players:
        if not remaining_player.is_host:
            remaining_player.is_ready = False

    lobby.status = "waiting"

    db.session.commit()

    return redirect(url_for("lobby_browser"))


@app.route("/lobby/<int:lobby_id>/chat", methods=["POST"])
def lobby_chat(lobby_id):
    if "username" not in session:
        return redirect(url_for("login"))

    username = session["username"]

    message_text = request.form.get("message", "").strip()

    if message_text:
        message = LobbyMessage(
            lobby_id=lobby_id,
            sender_name=username,
            message_text=message_text
        )
        db.session.add(message)
        db.session.commit()

    return redirect(url_for("lobby_page", lobby_id=lobby_id))


@app.route("/lobby/<int:lobby_id>/start", methods=["POST"])
def start_lobby_game_from_lobby(lobby_id):
    global game_state, game_log, game_chat_messages, last_roll, can_buy, game_over, waiting_for_ai, game_id
    global current_game_players, property_houses, property_landing_counts, restart_votes, active_context_game_id

    if "username" not in session:
        return redirect(url_for("login"))

    username = session["username"]

    lobby = db.session.get(Lobby, lobby_id)

    if lobby is None:
        return redirect(url_for("lobby_browser"))

    if lobby.status == "in_game":
        return redirect(url_for("game_page", game_id=f"lobby_{lobby.id}_game"))
    
    players_in_lobby = LobbyPlayer.query.filter_by(
        lobby_id=lobby.id
    ).all()

    current_player = LobbyPlayer.query.filter_by(
        lobby_id=lobby.id,
        player_name=username
    ).first()

    if current_player is None:
        return redirect(url_for("lobby_browser"))

    if not current_player.is_host:
        return redirect(url_for("lobby_page", lobby_id=lobby.id))

    if len(players_in_lobby) < lobby.max_players:
        return redirect(url_for(
            "lobby_page",
            lobby_id=lobby.id,
            start_error=f"The lobby is not full yet. Need {lobby.max_players} players."
        ))

    non_host_players = [
        player for player in players_in_lobby
        if not player.is_host
    ]

    if not all(player.is_ready for player in non_host_players):
        return redirect(url_for(
            "lobby_page",
            lobby_id=lobby.id,
            start_error="Not all players are ready yet."
        ))

    lobby.status = "in_game"
    db.session.commit()

    game_id = f"lobby_{lobby.id}_game"
    active_context_game_id = game_id
    session["active_game_id"] = game_id

    ordered_lobby_players = sorted(
        players_in_lobby,
        key=lambda lobby_player: lobby_player.joined_at
    )

    # Support 2-, 3-, and 4-player LAN games. Player ids are stable and
    # mapped to lobby join order.
    current_game_players = [
        {"player_id": f"player{index + 1}", "name": lobby_player.player_name}
        for index, lobby_player in enumerate(ordered_lobby_players[:4])
    ]

    game_state = engine.initialize_game(current_game_players)
    game_log = [make_game_log_entry("system", f"Game started from lobby: {lobby.name}. {current_game_players[0]['name']} is on GO.")]
    game_chat_messages = []
    last_roll = None
    clear_pending_buy()
    pending_jail_actions.clear()
    pending_jail_purchases.clear()
    game_over = False
    waiting_for_ai = False
    property_houses = {}
    property_landing_counts = {}
    restart_votes = set()

    return redirect(url_for("game_page", game_id=game_id))



@app.route("/lobby/start", methods=["POST"])
def start_lobby_game():
    global game_state, game_log, game_chat_messages, last_roll, can_buy, game_over, waiting_for_ai, game_id
    global current_game_players, property_houses, property_landing_counts, restart_votes, active_context_game_id

    game_id = "local_demo_game"
    active_context_game_id = game_id
    session["active_game_id"] = game_id
    current_game_players = list(players)
    game_state = engine.initialize_game(current_game_players)
    game_log = [{"type": "system", "message": "Game started! Player 1 is on GO."}]
    game_chat_messages = []
    last_roll = None
    clear_pending_buy()
    pending_jail_actions.clear()
    pending_jail_purchases.clear()
    game_over = False
    waiting_for_ai = False
    property_houses = {}
    property_landing_counts = {}
    restart_votes = set()
    lobby_demo_state = {
    "player2_ready": False,
    "messages": [
        {"sender": "System", "text": "Welcome to the lobby."},
        {"sender": "System", "text": "Waiting for more players to join."},
        {"sender": "Player 2", "text": "Ready when you are."}
    ]
}

    return redirect(url_for("game_page", game_id=game_id))

@app.route("/game/<game_id>/state")
def game_state_status(game_id):
    lobby = get_lobby_from_game_id(game_id)

    if lobby is None and str(game_id).startswith("lobby_"):
        return jsonify({
            "ok": True,
            "redirect_url": url_for("lobby_browser")
        })

    if lobby is not None and lobby.status != "in_game":
        return jsonify({
            "ok": True,
            "redirect_url": url_for("lobby_page", lobby_id=lobby.id)
        })

    player = get_visible_player()
    tile = get_visible_tile()
    second_player_id = get_other_player_id()
    second_player = game_state.players.get(second_player_id, player)
    active_player_id = get_active_player_id()
    current_user_player_id = get_current_user_player_id()

    state_signature = json.dumps({
        "game_id": game_id,
        "game_mode": current_game_mode(),
        "current_turn": active_player_id,
        "current_user_player_id": current_user_player_id,
        "player_position": player.pos,
        "second_player_position": second_player.pos,
        "all_players": get_all_player_view_models(),
        "money": player.cash,
        "second_player_money": second_player.cash,
        "can_buy": can_buy and pending_buy_player_id == current_user_player_id,
        "pending_buy_player_id": pending_buy_player_id,
        "pending_buy_tile_index": pending_buy_tile_index,
        "waiting_for_ai": waiting_for_ai,
        "game_over": game_over,
        "game_log_count": len(game_log),
        "game_chat_count": len(game_chat_messages),
        "property_houses": property_houses,
        "property_owners": {idx: state.owner_id for idx, state in game_state.properties.items()},
        "property_state_houses": {idx: state.houses for idx, state in game_state.properties.items()},
        "restart_votes": sorted(restart_votes),
    }, sort_keys=True)

    return jsonify({
        "ok": True,
        "game_id": game_id,
        "game_mode": current_game_mode(),
        "player_position": player.pos,
        "player_money": player.cash,
        "money": player.cash,
        "ai_position": second_player.pos,
        "second_player_position": second_player.pos,
        "ai_money": second_player.cash,
        "second_player_money": second_player.cash,
        "all_players": get_all_player_view_models(),
        "location": tile.name,
        "can_buy": can_buy and pending_buy_player_id == current_user_player_id,
        "game_over": game_over,
        "waiting_for_ai": waiting_for_ai,
        "current_turn": format_player_name(active_player_id),
        "current_user_player_id": current_user_player_id,
        "is_current_user_turn": current_user_can_act(),
        "winner": format_player_name(game_state.winner_id) if game_state.winner_id else None,
        "game_log": game_log,
        "game_log_count": len(game_log),
        "game_chat_count": len(game_chat_messages),
        "restart_votes_count": len(restart_votes),
        "restart_required_count": get_restart_required_count(),
        "restart_has_voted": current_user_player_id in restart_votes,
        "restart_vote_names": get_restart_vote_names(),
        "state_signature": state_signature,
        "html": render_game_html(),
    })

@app.route("/game-chat", methods=["POST"])
def game_chat():
    message_text = request.form.get("message", "").strip()

    if message_text:
        sender_name = format_player_name(get_current_user_player_id())

        game_chat_messages.append({
            "sender": sender_name,
            "text": message_text[:300]
        })

        # Keep the game page light by retaining only the latest messages.
        if len(game_chat_messages) > 50:
            del game_chat_messages[:-50]

    if is_ajax_request():
        return render_game_page()

    return redirect(url_for("game_page", game_id=game_id))


@app.route("/game/<game_id>/leave", methods=["POST"])
def leave_game_room(game_id):
    if "username" not in session:
        return redirect(url_for("login"))

    username = session["username"]

    lobby = get_lobby_from_game_id(game_id)

    if lobby is None:
        return redirect(url_for("lobby_browser"))

    player = LobbyPlayer.query.filter_by(
        lobby_id=lobby.id,
        player_name=username
    ).first()

    if player is None:
        return redirect(url_for("lobby_browser"))

    if player.is_host:
        db.session.delete(lobby)
        db.session.commit()
        return redirect(url_for("lobby_browser"))

    db.session.delete(player)

    remaining_players = LobbyPlayer.query.filter_by(
        lobby_id=lobby.id
    ).all()

    for remaining_player in remaining_players:
        if not remaining_player.is_host:
            remaining_player.is_ready = False

    lobby.status = "waiting"

    db.session.commit()

    return redirect(url_for("lobby_browser"))


@app.route("/game/<game_id>")
def game_page(game_id):
    update_buy_status()
    return render_game_page()


@app.route("/roll", methods=["POST"])
def roll_dice():
    if game_over or can_buy or waiting_for_ai:
        if is_ajax_request():
            return ajax_dice_response(last_roll)
        return redirect(url_for("game_page", game_id=game_id))

    if get_current_user_player_id() != get_active_player_id():
        if is_ajax_request():
            return ajax_dice_response(last_roll)
        return redirect(url_for("game_page", game_id=game_id))

    dice_result = process_active_turn(dice_result_for_response=True)

    if is_ajax_request():
        return ajax_dice_response(dice_result)

    return redirect(url_for("game_page", game_id=game_id))


@app.route("/buy", methods=["POST"])
def buy_property():
    global waiting_for_ai

    if game_over:
        if is_ajax_request():
            return render_game_page()
        return redirect(url_for("game_page", game_id=game_id))

    if not can_buy or pending_buy_player_id != get_current_user_player_id():
        if is_ajax_request():
            return render_game_page()
        return redirect(url_for("game_page", game_id=game_id))

    player = game_state.players[pending_buy_player_id]
    tile = config.tiles[pending_buy_tile_index]
    property_state = game_state.properties[tile.index]

    if property_state.owner_id is None and player.cash >= tile.buy_price:
        player.cash -= tile.buy_price
        property_state.owner_id = pending_buy_player_id
        append_game_log("property_bought", f"{format_player_name(pending_buy_player_id)} bought {tile.name} for ${tile.buy_price}.")
        record_event(
            "property_bought",
            amount=tile.buy_price,
            metadata={
                "player_id": pending_buy_player_id,
                "tile": tile.name
            }
        )
    else:
        append_game_log("action_blocked", f"{format_player_name(pending_buy_player_id)} cannot buy {tile.name}.")

    clear_pending_buy()

    if is_singleplayer_mode() and get_active_player_id() != "player1":
        waiting_for_ai = True
    else:
        waiting_for_ai = False

    update_buy_status()

    if is_ajax_request():
        return render_game_page()

    return redirect(url_for("game_page", game_id=game_id))


@app.route("/skip-buy", methods=["POST"])
def skip_buy():
    global waiting_for_ai

    if game_over:
        if is_ajax_request():
            return render_game_page()
        return redirect(url_for("game_page", game_id=game_id))

    if can_buy and pending_buy_player_id == get_current_user_player_id():
        tile = config.tiles[pending_buy_tile_index]
        append_game_log("property_skipped", f"{format_player_name(pending_buy_player_id)} chose not to buy {tile.name}.")
        clear_pending_buy()

    if is_singleplayer_mode() and get_active_player_id() != "player1":
        waiting_for_ai = True
    else:
        waiting_for_ai = False

    update_buy_status()

    if is_ajax_request():
        return render_game_page()

    return redirect(url_for("game_page", game_id=game_id))


@app.route("/ai-turn", methods=["POST"])
def ai_turn():
    global waiting_for_ai, last_roll

    # In LAN multiplayer there is no AI. The second turn must be taken by the real player2 browser.
    if not is_singleplayer_mode():
        waiting_for_ai = False
        if is_ajax_request():
            return ajax_dice_response(last_roll)
        return redirect(url_for("game_page", game_id=game_id))

    if game_over:
        if is_ajax_request():
            return ajax_dice_response(last_roll)
        return redirect(url_for("game_page", game_id=game_id))

    clear_pending_buy()

    while game_state.turn_order[game_state.current_turn_index] != "player1":
        acting_player_id = game_state.turn_order[game_state.current_turn_index]
        old_position = game_state.players[acting_player_id].pos
        ai_event = engine.take_turn(game_state, decision_provider)

        if "player_id" not in ai_event:
            ai_event["player_id"] = acting_player_id

        new_position = game_state.players[acting_player_id].pos
        last_roll = (new_position - old_position) % len(config.tiles)

        landed_tile = config.tiles[new_position]
        if landed_tile.tile_type == "property":
            record_property_landing(acting_player_id, landed_tile.index)

        perform_ai_property_management(acting_player_id)

        text = format_event(ai_event)

        if text and "landed on GO" not in text:
            append_game_log(ai_event.get("type", "ai_turn"), text)

        check_game_over()

        if game_over:
            waiting_for_ai = False
            if is_ajax_request():
                return ajax_dice_response(last_roll)
            return redirect(url_for("game_page", game_id=game_id))

    waiting_for_ai = False
    update_buy_status()

    if is_ajax_request():
        return ajax_dice_response(last_roll)

    return redirect(url_for("game_page", game_id=game_id))

@app.route("/jail/pay", methods=["POST"])
def jail_pay_fine():
    current_user_player_id = get_current_user_player_id()
    if not get_jail_action_info()["can_choose_jail_action"]:
        if is_ajax_request():
            return render_game_page()
        return redirect(url_for("game_page", game_id=game_id))

    pending_jail_actions[current_user_player_id] = {"choice": "pay_fine"}
    process_active_turn()

    if is_ajax_request():
        return render_game_page()
    return redirect(url_for("game_page", game_id=game_id))


@app.route("/jail/use-card", methods=["POST"])
def jail_use_card():
    current_user_player_id = get_current_user_player_id()
    info = get_jail_action_info()
    if not info["can_choose_jail_action"] or info["jail_cards"] <= 0:
        if is_ajax_request():
            return render_game_page()
        return redirect(url_for("game_page", game_id=game_id))

    pending_jail_actions[current_user_player_id] = {"choice": "use_card"}
    process_active_turn()

    if is_ajax_request():
        return render_game_page()
    return redirect(url_for("game_page", game_id=game_id))


@app.route("/jail/buy-card", methods=["POST"])
def jail_buy_card():
    current_user_player_id = get_current_user_player_id()
    info = get_jail_action_info()
    if not info["can_choose_jail_action"] or not info["jail_card_sellers"]:
        if is_ajax_request():
            return render_game_page()
        return redirect(url_for("game_page", game_id=game_id))

    seller_id = request.form.get("seller_id") or info["jail_card_sellers"][0]["player_id"]
    try:
        offer = int(request.form.get("offer", config.jail_fine))
    except (TypeError, ValueError):
        offer = config.jail_fine

    pending_jail_actions[current_user_player_id] = {
        "choice": "buy_card",
        "seller_id": seller_id,
        "offer": max(1, offer),
    }
    process_active_turn()

    if is_ajax_request():
        return render_game_page()
    return redirect(url_for("game_page", game_id=game_id))


@app.route("/build-house", methods=["POST"])
def build_house():
    global can_buy, waiting_for_ai

    if game_over:
        return redirect(url_for("game_page", game_id=game_id))

    current_user_player_id = get_current_user_player_id()
    player = game_state.players[current_user_player_id]

    try:
        tile_index = int(request.form.get("tile_index", -1))
    except (TypeError, ValueError):
        tile_index = -1

    property_state = game_state.properties.get(tile_index)
    if property_state is None:
        append_game_log("action_blocked", "No valid property was selected for building.")
    elif property_state.owner_id != current_user_player_id:
        append_game_log("action_blocked", f"{format_player_name(current_user_player_id)} cannot build on a property they do not own.")
    elif can_buy:
        append_game_log("action_blocked", "Please choose Buy or Skip before managing houses.")
    elif waiting_for_ai or game_over:
        append_game_log("action_blocked", "House management is not available right now.")
    else:
        tile = config.tiles[tile_index]
        current_houses = property_state.houses or property_houses.get(tile_index, 0)

        if current_houses >= MAX_HOUSES_PER_PROPERTY:
            append_game_log("action_blocked", f"{tile.name} already has the maximum number of houses.")
        elif player.cash < HOUSE_COST:
            append_game_log("action_blocked", f"{format_player_name(current_user_player_id)} needs ${HOUSE_COST} to build a house on {tile.name}.")
        else:
            player.cash -= HOUSE_COST
            property_state.houses = current_houses + 1
            property_houses[tile_index] = property_state.houses
            append_game_log(
                "house_built",
                f"{format_player_name(current_user_player_id)} built a house on {tile.name}. "
                f"Houses: {property_state.houses}/{MAX_HOUSES_PER_PROPERTY}."
            )
            record_event(
                "house_built",
                amount=HOUSE_COST,
                metadata={
                    "player_id": current_user_player_id,
                    "tile": tile.name,
                    "houses": property_state.houses,
                }
            )

    update_buy_status()

    if is_ajax_request():
        return render_game_page()

    return redirect(url_for("game_page", game_id=game_id))


@app.route("/sell-house", methods=["POST"])
def sell_house():
    global can_buy, waiting_for_ai

    if game_over:
        return redirect(url_for("game_page", game_id=game_id))

    current_user_player_id = get_current_user_player_id()
    player = game_state.players[current_user_player_id]

    try:
        tile_index = int(request.form.get("tile_index", -1))
    except (TypeError, ValueError):
        tile_index = -1

    property_state = game_state.properties.get(tile_index)
    if property_state is None:
        append_game_log("action_blocked", "No valid property was selected for selling a house.")
    elif property_state.owner_id != current_user_player_id:
        append_game_log("action_blocked", f"{format_player_name(current_user_player_id)} cannot sell a house on a property they do not own.")
    elif can_buy:
        append_game_log("action_blocked", "Please choose Buy or Skip before managing houses.")
    elif waiting_for_ai or game_over:
        append_game_log("action_blocked", "House management is not available right now.")
    elif not player_needs_cash(current_user_player_id):
        append_game_log("action_blocked", "You can only sell houses when you need cash.")
    else:
        current_houses = property_state.houses or property_houses.get(tile_index, 0)
        if current_houses <= 0:
            append_game_log("action_blocked", "No house was available to sell.")
        else:
            tile = config.tiles[tile_index]
            property_state.houses = current_houses - 1
            if property_state.houses > 0:
                property_houses[tile_index] = property_state.houses
            else:
                property_houses.pop(tile_index, None)

            player.cash += HOUSE_SELL_VALUE
            append_game_log("house_sold", f"{format_player_name(current_user_player_id)} sold one house on {tile.name} for ${HOUSE_SELL_VALUE}.")
            record_event(
                "house_sold",
                amount=HOUSE_SELL_VALUE,
                metadata={
                    "player_id": current_user_player_id,
                    "tile": tile.name,
                    "remaining_houses": property_state.houses,
                }
            )

    update_buy_status()

    if is_ajax_request():
        return render_game_page()

    return redirect(url_for("game_page", game_id=game_id))


@app.route("/sell-property", methods=["POST"])
def sell_property():
    global can_buy, waiting_for_ai

    if game_over:
        return redirect(url_for("game_page", game_id=game_id))

    current_user_player_id = get_current_user_player_id()
    player = game_state.players[current_user_player_id]

    try:
        tile_index = int(request.form.get("tile_index", -1))
    except (TypeError, ValueError):
        tile_index = -1

    property_state = game_state.properties.get(tile_index)
    if property_state is None:
        append_game_log("action_blocked", "No valid property was selected for selling.")
    elif property_state.owner_id != current_user_player_id:
        append_game_log("action_blocked", f"{format_player_name(current_user_player_id)} cannot sell a property they do not own.")
    elif can_buy:
        append_game_log("action_blocked", "Please choose Buy or Skip before selling property.")
    elif waiting_for_ai or game_over:
        append_game_log("action_blocked", "Property selling is not available right now.")
    elif not player_needs_cash(current_user_player_id):
        append_game_log("action_blocked", "You can only sell properties when you need cash.")
    else:
        tile = config.tiles[tile_index]
        house_count = property_state.houses or property_houses.get(tile_index, 0)
        sell_value = (tile.buy_price // 2) + (house_count * HOUSE_SELL_VALUE)

        player.cash += sell_value
        property_state.owner_id = None
        property_state.houses = 0
        property_state.has_hotel = False
        property_state.mortgaged = False
        property_houses.pop(tile_index, None)

        append_game_log(
            "property_sold",
            f"{format_player_name(current_user_player_id)} sold {tile.name} for ${sell_value}."
        )
        record_event(
            "property_sold",
            amount=sell_value,
            metadata={
                "player_id": current_user_player_id,
                "tile": tile.name,
                "houses_removed": house_count,
            }
        )

    update_buy_status()

    if is_ajax_request():
        return render_game_page()

    return redirect(url_for("game_page", game_id=game_id))

@app.route("/reset", methods=["POST"])
def reset_game():
    global game_state, game_log, game_chat_messages, last_roll, can_buy, game_over, waiting_for_ai, property_houses, property_landing_counts
    global current_game_players, restart_votes

    current_user_player_id = get_current_user_player_id()

    if is_singleplayer_mode():
        current_game_players = [
            {"player_id": "player1", "name": session.get("username", "Player 1")},
            {"player_id": "ai_1", "name": "AI Player"},
        ]
        restart_votes = set()
    else:
        # LAN multiplayer requires every real player to approve the restart.
        restart_votes.add(current_user_player_id)
        required_votes = set(game_state.turn_order)

        if not required_votes.issubset(restart_votes):
            append_game_log(
                "restart_requested",
                f"{format_player_name(current_user_player_id)} requested a restart "
                f"({len(restart_votes)}/{len(required_votes)} approvals)."
            )
            if is_ajax_request():
                return render_game_page()
            return redirect(url_for("game_page", game_id=game_id))

        append_game_log("restart_agreed", "All players agreed to restart the game.")
        restart_votes = set()

    game_state = engine.initialize_game(current_game_players)
    game_log = [make_game_log_entry("system", f"Game reset! {current_game_players[0]['name']} is on GO.")]
    game_chat_messages = []
    last_roll = None
    clear_pending_buy()
    pending_jail_actions.clear()
    pending_jail_purchases.clear()
    game_over = False
    waiting_for_ai = False
    property_houses = {}
    property_landing_counts = {}

    if is_ajax_request():
        return render_game_page()

    return redirect(url_for("game_page", game_id=game_id))


if __name__ == "__main__":
    with app.app_context():
        db.create_all()

    app.run(host="0.0.0.0", port=5000, debug=True)