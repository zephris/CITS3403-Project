from flask import Blueprint, jsonify, request

from template.backend.app.lobby.lobby_manager import LobbyManager


lobby_bp = Blueprint("lobby", __name__)

lobby_manager = LobbyManager()


@lobby_bp.route("/lobbies", methods=["POST"])
def create_lobby():
    data = request.get_json() or {}

    try:
        lobby = lobby_manager.create_lobby(
            host_id=data.get("host_id", "player1"),
            name=data.get("name", "New Lobby"),
            lobby_type=data.get("lobby_type", "public"),
            max_players=int(data.get("max_players", 4))
        )

        return jsonify(lobby_manager.lobby_to_dict(lobby)), 201

    except ValueError as error:
        return jsonify({"error": str(error)}), 400


@lobby_bp.route("/lobbies/public", methods=["GET"])
def list_public_lobbies():
    lobbies = lobby_manager.list_public_lobbies()

    return jsonify([
        lobby_manager.lobby_to_dict(lobby)
        for lobby in lobbies
    ]), 200


@lobby_bp.route("/lobbies/<int:lobby_id>/join", methods=["POST"])
def join_lobby(lobby_id):
    data = request.get_json() or {}

    try:
        lobby = lobby_manager.join_lobby(
            lobby_id=lobby_id,
            player_id=data.get("player_id", "player2")
        )

        return jsonify(lobby_manager.lobby_to_dict(lobby)), 200

    except ValueError as error:
        return jsonify({"error": str(error)}), 400


@lobby_bp.route("/lobbies/join-by-code", methods=["POST"])
def join_lobby_by_code():
    data = request.get_json() or {}

    try:
        lobby = lobby_manager.join_lobby_by_code(
            invite_code=data.get("invite_code", ""),
            player_id=data.get("player_id", "player2")
        )

        return jsonify(lobby_manager.lobby_to_dict(lobby)), 200

    except ValueError as error:
        return jsonify({"error": str(error)}), 400


@lobby_bp.route("/lobbies/<int:lobby_id>/leave", methods=["POST"])
def leave_lobby(lobby_id):
    data = request.get_json() or {}

    try:
        lobby = lobby_manager.leave_lobby(
            lobby_id=lobby_id,
            player_id=data.get("player_id", "player2")
        )

        return jsonify(lobby_manager.lobby_to_dict(lobby)), 200

    except ValueError as error:
        return jsonify({"error": str(error)}), 400


@lobby_bp.route("/lobbies/<int:lobby_id>/ready", methods=["POST"])
def set_ready(lobby_id):
    data = request.get_json() or {}

    try:
        lobby = lobby_manager.set_ready(
            lobby_id=lobby_id,
            player_id=data.get("player_id", "player2"),
            ready=bool(data.get("ready", True))
        )

        return jsonify(lobby_manager.lobby_to_dict(lobby)), 200

    except ValueError as error:
        return jsonify({"error": str(error)}), 400


@lobby_bp.route("/lobbies/<int:lobby_id>/start", methods=["POST"])
def start_game(lobby_id):
    data = request.get_json() or {}

    try:
        result = lobby_manager.start_game(
            lobby_id=lobby_id,
            host_id=data.get("host_id", "player1")
        )

        return jsonify(result), 200

    except ValueError as error:
        return jsonify({"error": str(error)}), 400