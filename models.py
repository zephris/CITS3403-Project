from datetime import datetime
import random
import string

from flask_sqlalchemy import SQLAlchemy


db = SQLAlchemy()

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), nullable=False, unique=True)
    password_hash = db.Column(db.String(255), nullable=False)
    bio = db.Column(db.String(300), nullable=False, default="Monopoly Perth player")
    profile_public = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

class Lobby(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False)
    lobby_type = db.Column(db.String(20), nullable=False, default="public")
    host_name = db.Column(db.String(80), nullable=False, default="Player 1")
    max_players = db.Column(db.Integer, nullable=False, default=4)
    invite_code = db.Column(db.String(8), nullable=False, unique=True)
    status = db.Column(db.String(20), nullable=False, default="waiting")
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    players = db.relationship(
        "LobbyPlayer",
        backref="lobby",
        cascade="all, delete-orphan"
    )

    messages = db.relationship(
        "LobbyMessage",
        backref="lobby",
        cascade="all, delete-orphan"
    )

    @staticmethod
    def generate_invite_code():
        return "".join(random.choices(string.ascii_uppercase + string.digits, k=8))


class LobbyPlayer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    lobby_id = db.Column(db.Integer, db.ForeignKey("lobby.id"), nullable=False)
    player_name = db.Column(db.String(80), nullable=False)
    is_host = db.Column(db.Boolean, nullable=False, default=False)
    is_ready = db.Column(db.Boolean, nullable=False, default=False)
    joined_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class LobbyMessage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    lobby_id = db.Column(db.Integer, db.ForeignKey("lobby.id"), nullable=False)
    sender_name = db.Column(db.String(80), nullable=False)
    message_text = db.Column(db.String(300), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)