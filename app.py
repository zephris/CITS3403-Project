from flask import Flask, render_template, redirect, url_for, request, session
from werkzeug.security import generate_password_hash, check_password_hash
from models import db, User, Lobby, LobbyPlayer, LobbyMessage
from template.backend.app.game_logic.engine import load_game_config, GameEngine
import random

app = Flask(__name__)
app.secret_key = "dev-secret-key"

app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///app.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db.init_app(app)


def get_current_username():
    return session.get("username")


config = load_game_config("template/backend/app/game_logic/data/monopoly_standard.json")
engine = GameEngine(config)

players = [
    {"player_id": "player1", "name": "Player 1"},
    {"player_id": "ai_1", "name": "AI Player"},
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
lobby_demo_state = {
    "player2_ready": False,
    "messages": [
        {"sender": "System", "text": "Welcome to the lobby."},
        {"sender": "System", "text": "Waiting for more players to join."},
        {"sender": "Player 2", "text": "Ready when you are."},
    ],
}
lobby_browser_state = {
    "lobbies": [
        {
            "id": 1,
            "name": "Perth Room 1",
            "host": "Player 1",
            "players": 2,
            "max_players": 4,
            "status": "Waiting",
        },
        {
            "id": 2,
            "name": "WA Monopoly Fans",
            "host": "Anthony",
            "players": 4,
            "max_players": 4,
            "status": "Full",
        },
        {
            "id": 3,
            "name": "City Match",
            "host": "Shuo",
            "players": 1,
            "max_players": 4,
            "status": "Waiting",
        },
        {
            "id": 4,
            "name": "Late Night Game",
            "host": "Dazai",
            "players": 3,
            "max_players": 4,
            "status": "Starting Soon",
        },
    ],
    "next_lobby_id": 5,
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

    print(
        {
            "game_id": game_id,
            "event_type": event_type,
            "amount": amount,
            "metadata": metadata,
        }
    )


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
                "turns_taken": getattr(player, "turns_taken", 0),
            },
            {
                "user_id": "ai_1",
                "final_rank": 1 if game_state.winner_id == "ai_1" else 2,
                "bankrupt_flag": getattr(ai_player, "bankrupt", False),
                "turns_taken": getattr(ai_player, "turns_taken", 0),
            },
        ],
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
        game_log.append(
            f"Game over! Winner: {format_player_name(game_state.winner_id)}"
        )
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
        winner=(
            format_player_name(game_state.winner_id) if game_state.winner_id else None
        ),
        current_turn=format_player_name(
            game_state.turn_order[game_state.current_turn_index]
        ),
        property_owners=property_owners,
        game_id=game_id,
    )


@app.route("/")
def home():
    return render_template("home.html", username=session.get("username"))


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()

        if not username or not password:
            return render_template(
                "register.html", error="Username and password are required."
            )

        existing_user = User.query.filter_by(username=username).first()

        if existing_user:
            return render_template("register.html", error="Username already exists.")

        new_user = User(
            username=username, password_hash=generate_password_hash(password)
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
            return render_template("login.html", error="Invalid username or password.")

        session["user_id"] = user.id
        session["username"] = user.username

        return redirect(url_for("home"))

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))


@app.route("/profile")
def profile():
    if "username" not in session:
        return redirect(url_for("login"))

    username = session["username"]

    user = User.query.filter_by(username=username).first()

    hosted_lobbies = (
        Lobby.query.filter_by(host_name=username)
        .order_by(Lobby.created_at.desc())
        .all()
    )

    joined_lobby_players = (
        LobbyPlayer.query.filter_by(player_name=username)
        .order_by(LobbyPlayer.joined_at.desc())
        .all()
    )

    joined_lobbies = [lobby_player.lobby for lobby_player in joined_lobby_players]

    total_lobbies = len(joined_lobbies)
    hosted_count = len(hosted_lobbies)

    return render_template(
        "profile.html",
        user=user,
        username=username,
        total_lobbies=total_lobbies,
        hosted_count=hosted_count,
        joined_lobbies=joined_lobbies,
    )


@app.route("/browser")
def lobby_browser():
    if "username" not in session:
        return redirect(url_for("login"))

    search_text = request.args.get("search", "").strip()

    query = Lobby.query

    if search_text:
        query = query.filter(
            db.or_(
                Lobby.name.ilike(f"%{search_text}%"),
                Lobby.host_name.ilike(f"%{search_text}%"),
            )
        )

    lobbies = query.order_by(Lobby.created_at.desc()).all()

    open_rooms = Lobby.query.filter(Lobby.status == "waiting").count()

    return render_template(
        "lobby_browser.html",
        lobbies=lobbies,
        search_text=search_text,
        online_players=12,
        open_rooms=open_rooms,
    )


@app.route("/browser/create", methods=["POST"])
def create_browser_lobby():
    if "username" not in session:
        return redirect(url_for("login"))

    username = session["username"]

    lobby_name = request.form.get("lobby_name", "").strip()
    max_players = int(request.form.get("max_players", 4))

    if not lobby_name:
        lobby_name = "New Lobby"

    max_players = max(2, min(max_players, 4))

    new_lobby = Lobby(
        name=lobby_name,
        lobby_type="public",
        host_name=username,
        max_players=max_players,
        invite_code=Lobby.generate_invite_code(),
        status="waiting",
    )

    db.session.add(new_lobby)
    db.session.commit()

    host_player = LobbyPlayer(
        lobby_id=new_lobby.id, player_name=username, is_host=True, is_ready=True
    )

    welcome_message = LobbyMessage(
        lobby_id=new_lobby.id,
        sender_name="System",
        message_text="Welcome to the lobby.",
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

    if lobby.status != "waiting":
        return redirect(url_for("lobby_browser"))

    if len(lobby.players) >= lobby.max_players:
        lobby.status = "full"
        db.session.commit()
        return redirect(url_for("lobby_browser"))

    existing_player = LobbyPlayer.query.filter_by(
        lobby_id=lobby.id, player_name=username
    ).first()

    if existing_player is None:
        player = LobbyPlayer(
            lobby_id=lobby.id, player_name=username, is_host=False, is_ready=False
        )
        db.session.add(player)

    if len(lobby.players) + 1 >= lobby.max_players:
        lobby.status = "full"

    db.session.commit()

    return redirect(url_for("lobby_page", lobby_id=lobby.id))


@app.route("/browser/quick-join", methods=["POST"])
def quick_join_lobby():
    lobbies = (
        Lobby.query.filter_by(status="waiting").order_by(Lobby.created_at.asc()).all()
    )

    for lobby in lobbies:
        if len(lobby.players) < lobby.max_players:
            return redirect(url_for("join_browser_lobby", lobby_id=lobby.id))

    return redirect(url_for("lobby_browser"))


@app.route("/lobby/<int:lobby_id>")
def lobby_page(lobby_id):
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

    player_count = len(players)
    lobby_status = (
        "All players are ready."
        if players and all(player.is_ready for player in players)
        else "Waiting for players..."
    )

    return render_template(
        "waiting_lobby.html",
        lobby=lobby,
        players=players,
        messages=messages,
        player_count=player_count,
        lobby_status=lobby_status,
    )


@app.route("/lobby/<int:lobby_id>/ready", methods=["POST"])
def toggle_lobby_ready(lobby_id):
    if "username" not in session:
      return redirect(url_for("login"))

    username = session["username"]
    
    player = LobbyPlayer.query.filter_by(
        lobby_id=lobby_id, player_name=username
    ).first()

    if player is None:
        player = LobbyPlayer(
            lobby_id=lobby_id, player_name=username, is_host=False, is_ready=False
        )
        db.session.add(player)

    player.is_ready = not player.is_ready
    db.session.commit()

    return redirect(url_for("lobby_page", lobby_id=lobby_id))


@app.route("/lobby/<int:lobby_id>/leave", methods=["POST"])
def leave_lobby(lobby_id):
    if "username" not in session:
        return redirect(url_for("login"))

    username = session["username"]

    player = LobbyPlayer.query.filter_by(
        lobby_id=lobby_id,
        player_name=username
    ).first()

    if player:
        db.session.delete(player)
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

    lobby = db.session.get(Lobby, lobby_id)

    if lobby is None:
        return redirect(url_for("lobby_browser"))

    lobby.status = "in_game"
    db.session.commit()

    game_id = f"lobby_{lobby.id}_game"
    game_state = engine.initialize_game(players)
    game_log = [f"Game started from lobby: {lobby.name}. Player 1 is on GO."]
    last_roll = None
    can_buy = False
    game_over = False
    waiting_for_ai = False

    return redirect(url_for("game_page", game_id=game_id))


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
    lobby_demo_state = {
        "player2_ready": False,
        "messages": [
            {"sender": "System", "text": "Welcome to the lobby."},
            {"sender": "System", "text": "Waiting for more players to join."},
            {"sender": "Player 2", "text": "Ready when you are."},
        ],
    }

    return redirect(url_for("game_page", game_id=game_id))


@app.route("/singleplayer")
def singleplayer():
    global game_state, game_log, last_roll, can_buy, game_over, waiting_for_ai, game_id

    game_id = "singleplayer_game"
    game_state = engine.initialize_game(players)
    game_log = ["Single player game started! Player 1 is on GO."]
    last_roll = None
    can_buy = False
    game_over = False
    waiting_for_ai = False

    return redirect(url_for("game_page", game_id=game_id))


@app.route("/game/<game_id>")
def game_page(game_id):
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
                metadata={"player_id": "player1", "tile": tile.name},
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


if __name__ == "__main__":
    with app.app_context():
        db.create_all()

    app.run(debug=True)
