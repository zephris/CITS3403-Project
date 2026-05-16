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
game_log = ["Game started! Player 1 is on GO."]
last_roll = None
can_buy = False
game_over = False
waiting_for_ai = False

# Pending property-purchase state. The game engine advances the turn immediately,
# so we store who landed on an unowned property until they click Buy or Skip.
pending_buy_player_id = None
pending_buy_tile_index = None

# Local house tracking for Shuo's enhanced UI.
# Key: tile index, Value: number of houses on that property.
property_houses = {}
MAX_HOUSES_PER_PROPERTY = 4
HOUSE_COST = 50
HOUSE_RENT_BONUS = 25
HOUSE_SELL_VALUE = 25

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
        return {"choice": "roll"}

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



def is_ajax_request():
    return request.headers.get("X-Requested-With") == "XMLHttpRequest"


def current_game_mode():
    return "singleplayer" if is_singleplayer_mode() else "multiplayer"


def get_active_player_id():
    return game_state.turn_order[game_state.current_turn_index]


def get_active_property_info():
    """
    Build the data used by the property-management panel.

    Important change:
    - Building houses is no longer tied to landing on the same property again.
    - Any property owned by the current player can be improved from the side panel.
    - Selling houses/properties is also handled from the same panel.
    """
    tile = get_pending_buy_tile() or get_visible_tile()
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

    # Do not allow other actions while the current player still has to decide Buy/Skip.
    management_allowed = (
        not waiting_for_ai
        and not game_over
        and not can_buy
    )

    for tile_index, property_state in game_state.properties.items():
        if property_state.owner_id != current_user_player_id:
            continue

        tile_obj = config.tiles[tile_index]
        house_count = property_state.houses or property_houses.get(tile_index, 0)
        property_state.houses = house_count
        if house_count > 0:
            property_houses[tile_index] = house_count
        else:
            property_houses.pop(tile_index, None)

        if management_allowed and house_count < MAX_HOUSES_PER_PROPERTY and player.cash >= HOUSE_COST:
            info["buildable_house_properties"].append({
                "tile_index": tile_index,
                "name": tile_obj.name,
                "houses": house_count,
                "next_houses": house_count + 1,
                "cost": HOUSE_COST,
            })

        if management_allowed and house_count > 0:
            info["sellable_house_properties"].append({
                "tile_index": tile_index,
                "name": tile_obj.name,
                "houses": house_count,
                "sell_value": HOUSE_SELL_VALUE,
            })

        if management_allowed:
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

def build_game_template_context(dice_result=None):
    player = get_visible_player()
    tile = get_visible_tile()

    current_user_player_id = get_current_user_player_id()
    second_player_id = get_other_player_id()
    second_player = game_state.players.get(second_player_id, player)

    player_ids = game_state.turn_order or list(game_state.players.keys())
    human_icons = ["🧍", "👤", "🧑", "🧑\u200d💼"]
    human_index = 0
    players = []

    for player_id in player_ids:
        game_player = game_state.players[player_id]
        is_ai = player_id.startswith("ai")
        if is_ai:
            icon = "🤖"
        else:
            icon = human_icons[human_index % len(human_icons)]
            human_index += 1

        players.append({
            "player_id": player_id,
            "name": game_player.name,
            "money": game_player.cash,
            "position": game_player.pos,
            "is_ai": is_ai,
            "icon": icon,
            "is_current_user": player_id == current_user_player_id,
        })

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
    active_player = game_state.players.get(active_player_id)
    active_player_icon = next(
        (entry["icon"] for entry in players if entry["player_id"] == active_player_id),
        "🧍"
    )

    tokens_by_tile = {}
    for slot_index, player_entry in enumerate(players, start=1):
        position_key = str(player_entry["position"])
        tokens_by_tile.setdefault(position_key, []).append({
            "icon": player_entry["icon"],
            "slot": slot_index,
            "is_ai": player_entry["is_ai"],
        })

    return {
        "position": player.pos,
        "location": tile.name,
        "waiting_for_ai": waiting_for_ai,
        "money": player.cash,
        "ai_money": second_player.cash,
        "ai_position": second_player.pos,
        "dice_result": dice_result,
        "game_log": game_log,
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
        "tokens_by_tile_json": json.dumps(tokens_by_tile),
        "players": players,
        "active_player_name": active_player.name if active_player else "Player",
        "active_player_icon": active_player_icon,
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
        "html": render_game_html(dice_result),
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
    global game_state, game_log, last_roll, can_buy, game_over, waiting_for_ai, game_id
    global property_houses, current_game_players

    game_id = "local_demo_game"
    current_game_players = [
        {"player_id": "player1", "name": session.get("username", "Player 1")},
        {"player_id": "ai_1", "name": "AI Player"},
    ]
    game_state = engine.initialize_game(current_game_players)
    game_log = ["Singleplayer game started! Player 1 is on GO."]
    last_roll = None
    clear_pending_buy()
    game_over = False
    waiting_for_ai = False
    property_houses = {}

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

@app.route("/browser")
def lobby_browser():
    search_text = request.args.get("search", "").strip()

    query = Lobby.query

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
    lobbies = Lobby.query.filter_by(status="waiting").order_by(Lobby.created_at.asc()).all()

    for lobby in lobbies:
        if len(lobby.players) < lobby.max_players:
            return redirect(url_for("join_browser_lobby", lobby_id=lobby.id))

    return redirect(url_for("lobby_browser"))

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

    minimum_players = 2
    non_host_players_ready = all(
        player.is_ready for player in non_host_players
    )

    can_start_game = (
        is_host
        and player_count >= minimum_players
        and non_host_players_ready
    )

    if player_count < minimum_players:
        lobby_status = f"Waiting for players... {player_count} / {minimum_players}"
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
            "game_url": None
        })

    game_url = None

    if lobby.status == "in_game":
        game_url = url_for("game_page", game_id=f"lobby_{lobby.id}_game")

    return jsonify({
        "exists": True,
        "status": lobby.status,
        "game_url": game_url
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

    was_host = player.is_host
    db.session.delete(player)

    remaining_players = LobbyPlayer.query.filter_by(
        lobby_id=lobby_id
    ).order_by(LobbyPlayer.joined_at.asc()).all()

    if not remaining_players:
        db.session.delete(lobby)
        db.session.commit()
        return redirect(url_for("lobby_browser"))

    if was_host:
        new_host = remaining_players[0]
        new_host.is_host = True
        lobby.host_name = new_host.player_name
        db.session.add(LobbyMessage(
            lobby_id=lobby.id,
            sender_name="System",
            message_text=f"{new_host.player_name} is now the host."
        ))

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
    global game_state, game_log, last_roll, can_buy, game_over, waiting_for_ai, game_id
    global current_game_players, property_houses

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

    minimum_players = 2
    if len(players_in_lobby) < minimum_players:
        return redirect(url_for(
            "lobby_page",
            lobby_id=lobby.id,
            start_error=f"At least {minimum_players} human players are required to start."
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

    ordered_lobby_players = sorted(
        players_in_lobby,
        key=lambda lobby_player: lobby_player.joined_at
    )

    current_game_players = []
    for index, lobby_player in enumerate(ordered_lobby_players, start=1):
        current_game_players.append({
            "player_id": f"player{index}",
            "name": lobby_player.player_name,
        })

    bot_slots = max(0, lobby.max_players - len(current_game_players))
    existing_ids = {player["player_id"] for player in current_game_players}
    bot_index = 1
    while len(current_game_players) < lobby.max_players and bot_index <= bot_slots:
        bot_id = f"ai_{bot_index}"
        if bot_id in existing_ids:
            bot_index += 1
            continue

        current_game_players.append({
            "player_id": bot_id,
            "name": f"Bot {bot_index}",
        })
        existing_ids.add(bot_id)
        bot_index += 1

    game_state = engine.initialize_game(current_game_players)
    game_log = [f"Game started from lobby: {lobby.name}. {current_game_players[0]['name']} is on GO."]
    last_roll = None
    clear_pending_buy()
    game_over = False
    waiting_for_ai = False
    property_houses = {}

    return redirect(url_for("game_page", game_id=game_id))



@app.route("/lobby/start", methods=["POST"])
def start_lobby_game():
    global game_state, game_log, last_roll, can_buy, game_over, waiting_for_ai, game_id
    global current_game_players

    game_id = "local_demo_game"
    current_game_players = list(players)
    game_state = engine.initialize_game(current_game_players)
    game_log = ["Game started! Player 1 is on GO."]
    last_roll = None
    clear_pending_buy()
    game_over = False
    waiting_for_ai = False
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
    player = get_visible_player()
    tile = get_visible_tile()
    second_player_id = get_other_player_id()
    second_player = game_state.players.get(second_player_id, player)
    active_player_id = get_active_player_id()
    current_user_player_id = get_current_user_player_id()
    player_ids = game_state.turn_order or list(game_state.players.keys())
    player_snapshot = [
        {
            "player_id": player_id,
            "position": game_state.players[player_id].pos,
            "money": game_state.players[player_id].cash,
        }
        for player_id in player_ids
    ]

    state_signature = json.dumps({
        "game_id": game_id,
        "game_mode": current_game_mode(),
        "current_turn": active_player_id,
        "current_user_player_id": current_user_player_id,
        "player_position": player.pos,
        "second_player_position": second_player.pos,
        "money": player.cash,
        "second_player_money": second_player.cash,
        "players": player_snapshot,
        "can_buy": can_buy and pending_buy_player_id == current_user_player_id,
        "pending_buy_player_id": pending_buy_player_id,
        "pending_buy_tile_index": pending_buy_tile_index,
        "waiting_for_ai": waiting_for_ai,
        "game_over": game_over,
        "game_log_count": len(game_log),
        "property_houses": property_houses,
        "property_owners": {idx: state.owner_id for idx, state in game_state.properties.items()},
        "property_state_houses": {idx: state.houses for idx, state in game_state.properties.items()},
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
        "players": player_snapshot,
        "state_signature": state_signature,
        "html": render_game_html(),
    })


@app.route("/game/<game_id>")
def game_page(game_id):
    update_buy_status()
    return render_game_page()


@app.route("/roll", methods=["POST"])
def roll_dice():
    global last_roll, can_buy, waiting_for_ai

    if game_over:
        if is_ajax_request():
            return ajax_dice_response(last_roll)
        return redirect(url_for("game_page", game_id=game_id))

    if can_buy:
        if is_ajax_request():
            return ajax_dice_response(last_roll)
        return redirect(url_for("game_page", game_id=game_id))

    if waiting_for_ai:
        if is_ajax_request():
            return ajax_dice_response(last_roll)
        return redirect(url_for("game_page", game_id=game_id))

    if get_current_user_player_id() != get_active_player_id():
        if is_ajax_request():
            return ajax_dice_response(last_roll)
        return redirect(url_for("game_page", game_id=game_id))

    clear_pending_buy()

    acting_player_id = get_active_player_id()
    old_position = game_state.players[acting_player_id].pos
    event = engine.take_turn(game_state, decision_provider)

    if "player_id" not in event:
        event["player_id"] = acting_player_id

    new_position = game_state.players[acting_player_id].pos
    last_roll = (new_position - old_position) % len(config.tiles)

    text = format_event(event)
    if text:
        game_log.append(text)

    maybe_create_pending_buy(acting_player_id)
    check_game_over()

    if not game_over and not can_buy and is_singleplayer_mode() and get_active_player_id() != "player1":
        waiting_for_ai = True
    else:
        waiting_for_ai = False

    if is_ajax_request():
        return ajax_dice_response(last_roll)

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
        game_log.append(f"{format_player_name(pending_buy_player_id)} bought {tile.name} for ${tile.buy_price}.")
        record_event(
            "property_bought",
            amount=tile.buy_price,
            metadata={
                "player_id": pending_buy_player_id,
                "tile": tile.name
            }
        )
    else:
        game_log.append(f"{format_player_name(pending_buy_player_id)} cannot buy {tile.name}.")

    clear_pending_buy()

    if is_singleplayer_mode() and get_active_player_id() != "player1":
        waiting_for_ai = True
        play_ai_turns_until_player()
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
        game_log.append(f"{format_player_name(pending_buy_player_id)} chose not to buy {tile.name}.")
        clear_pending_buy()

    if is_singleplayer_mode() and get_active_player_id() != "player1":
        waiting_for_ai = True
        play_ai_turns_until_player()
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

        text = format_event(ai_event)

        if text and "landed on GO" not in text:
            game_log.append(text)

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
        game_log.append("No valid property was selected for building.")
    elif property_state.owner_id != current_user_player_id:
        game_log.append(f"{format_player_name(current_user_player_id)} cannot build on a property they do not own.")
    elif can_buy:
        game_log.append("Please choose Buy or Skip before managing houses.")
    elif waiting_for_ai or game_over:
        game_log.append("House management is not available right now.")
    else:
        tile = config.tiles[tile_index]
        current_houses = property_state.houses or property_houses.get(tile_index, 0)

        if current_houses >= MAX_HOUSES_PER_PROPERTY:
            game_log.append(f"{tile.name} already has the maximum number of houses.")
        elif player.cash < HOUSE_COST:
            game_log.append(f"{format_player_name(current_user_player_id)} needs ${HOUSE_COST} to build a house on {tile.name}.")
        else:
            player.cash -= HOUSE_COST
            property_state.houses = current_houses + 1
            property_houses[tile_index] = property_state.houses
            game_log.append(
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
        game_log.append("No valid property was selected for selling a house.")
    elif property_state.owner_id != current_user_player_id:
        game_log.append(f"{format_player_name(current_user_player_id)} cannot sell a house on a property they do not own.")
    elif can_buy:
        game_log.append("Please choose Buy or Skip before managing houses.")
    elif waiting_for_ai or game_over:
        game_log.append("House management is not available right now.")
    else:
        current_houses = property_state.houses or property_houses.get(tile_index, 0)
        if current_houses <= 0:
            game_log.append("No house was available to sell.")
        else:
            tile = config.tiles[tile_index]
            property_state.houses = current_houses - 1
            if property_state.houses > 0:
                property_houses[tile_index] = property_state.houses
            else:
                property_houses.pop(tile_index, None)

            player.cash += HOUSE_SELL_VALUE
            game_log.append(f"{format_player_name(current_user_player_id)} sold one house on {tile.name} for ${HOUSE_SELL_VALUE}.")
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
        game_log.append("No valid property was selected for selling.")
    elif property_state.owner_id != current_user_player_id:
        game_log.append(f"{format_player_name(current_user_player_id)} cannot sell a property they do not own.")
    elif can_buy:
        game_log.append("Please choose Buy or Skip before selling property.")
    elif waiting_for_ai or game_over:
        game_log.append("Property selling is not available right now.")
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

        game_log.append(
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
    global game_state, game_log, last_roll, can_buy, game_over, waiting_for_ai, property_houses
    global current_game_players

    if is_singleplayer_mode():
        current_game_players = [
            {"player_id": "player1", "name": session.get("username", "Player 1")},
            {"player_id": "ai_1", "name": "AI Player"},
        ]

    game_state = engine.initialize_game(current_game_players)
    game_log = ["Game reset! Player 1 is on GO."]
    last_roll = None
    clear_pending_buy()
    game_over = False
    waiting_for_ai = False
    property_houses = {}

    if is_ajax_request():
        return render_game_page()

    return redirect(url_for("game_page", game_id=game_id))


if __name__ == "__main__":
    with app.app_context():
        db.create_all()

    app.run(host="0.0.0.0", port=5000, debug=True)