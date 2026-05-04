from flask import Flask, render_template, session, redirect, url_for
import random

app = Flask(__name__)
app.secret_key = "dev-secret-key"


board_positions = [
    "GO",
    "Hay Street",
    "Community Chest",
    "Murray St",
    "Income Tax",
    "Perth Station",
    "Barrack St",
    "Chance",
    "Wellington St",
    "William St",
    "In Jail",
    "Elizabeth Quay",
    "Synergy",
    "Bell Tower",
    "Swan River",
    "Fremantle Station",
    "Fremantle Prison",
    "Community Chest",
    "Fremantle Markets",
    "Cappuccino Strip",
    "Free Parking",
    "Kings Park",
    "Chance",
    "Botanic Garden",
    "War Memorial",
    "Midland Station",
    "Scarborough Beach",
    "Water Corp",
    "City Beach",
    "Cottesloe Beach",
    "Go To Jail",
    "Northbridge",
    "Leederville",
    "Community Chest",
    "Subiaco",
    "Joondalup Station",
    "Chance",
    "Crown Perth",
    "Luxury Tax",
    "St Georges Tce"
]


@app.route("/")
def home():
    if "player_position" not in session:
        session["player_position"] = 0
        session["player_money"] = 1500
        session["game_log"] = ["Game started! Player 1 is on GO."]

    return render_template(
        "index.html",
        position=session["player_position"],
        location=board_positions[session["player_position"]],
        money=session["player_money"],
        dice_result=None,
        game_log=session["game_log"]
    )


@app.route("/roll")
def roll_dice():
    dice_result = random.randint(1, 6)

    old_position = session.get("player_position", 0)
    new_position = (old_position + dice_result) % len(board_positions)

    session["player_position"] = new_position

    if new_position < old_position:
        session["player_money"] += 200
        session["game_log"].append("Player 1 passed GO and collected $200.")

    session["game_log"].append(
        f"Player 1 rolled a {dice_result} and landed on {board_positions[new_position]}."
    )

    session.modified = True

    return render_template(
        "index.html",
        position=session["player_position"],
        location=board_positions[session["player_position"]],
        money=session["player_money"],
        dice_result=dice_result,
        game_log=session["game_log"]
    )


@app.route("/reset")
def reset_game():
    session.clear()
    return redirect(url_for("home"))


if __name__ == "__main__":
    app.run(debug=True)