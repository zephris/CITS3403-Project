from dataclasses import dataclass, field
from typing import Dict, List
import random
import string


@dataclass
class Lobby:
    lobby_id: int
    name: str
    lobby_type: str
    host_id: str
    max_players: int
    invite_code: str
    players: List[str] = field(default_factory=list)
    ready_status: Dict[str, bool] = field(default_factory=dict)
    is_open: bool = True


class LobbyManager:
    def __init__(self):
        self.lobbies: Dict[int, Lobby] = {}
        self.next_lobby_id = 1

    def create_lobby(self, host_id: str, name: str, lobby_type: str = "public", max_players: int = 4) -> Lobby:
        if lobby_type not in ["public", "private", "single"]:
            raise ValueError("Invalid lobby type")

        if lobby_type == "single":
            max_players = 1
        else:
            max_players = max(2, min(max_players, 4))

        lobby = Lobby(
            lobby_id=self.next_lobby_id,
            name=name,
            lobby_type=lobby_type,
            host_id=host_id,
            max_players=max_players,
            invite_code=self._generate_invite_code()
        )

        lobby.players.append(host_id)
        lobby.ready_status[host_id] = False

        self.lobbies[self.next_lobby_id] = lobby
        self.next_lobby_id += 1

        return lobby

    def list_public_lobbies(self) -> List[Lobby]:
        return [
            lobby for lobby in self.lobbies.values()
            if lobby.lobby_type == "public" and lobby.is_open
        ]

    def join_lobby(self, lobby_id: int, player_id: str) -> Lobby:
        lobby = self._get_lobby(lobby_id)

        if not lobby.is_open:
            raise ValueError("Lobby is closed")

        if player_id in lobby.players:
            return lobby

        if len(lobby.players) >= lobby.max_players:
            raise ValueError("Lobby is full")

        lobby.players.append(player_id)
        lobby.ready_status[player_id] = False

        return lobby

    def join_lobby_by_code(self, invite_code: str, player_id: str) -> Lobby:
        for lobby in self.lobbies.values():
            if lobby.invite_code == invite_code:
                return self.join_lobby(lobby.lobby_id, player_id)

        raise ValueError("Invite code not found")

    def leave_lobby(self, lobby_id: int, player_id: str) -> Lobby:
        lobby = self._get_lobby(lobby_id)

        if player_id not in lobby.players:
            raise ValueError("Player is not in this lobby")

        lobby.players.remove(player_id)
        lobby.ready_status.pop(player_id, None)

        if player_id == lobby.host_id:
            if lobby.players:
                lobby.host_id = lobby.players[0]
            else:
                lobby.is_open = False

        return lobby

    def set_ready(self, lobby_id: int, player_id: str, ready: bool) -> Lobby:
        lobby = self._get_lobby(lobby_id)

        if player_id not in lobby.players:
            raise ValueError("Player is not in this lobby")

        lobby.ready_status[player_id] = ready

        return lobby

    def can_start_game(self, lobby_id: int, host_id: str) -> bool:
        lobby = self._get_lobby(lobby_id)

        if lobby.host_id != host_id:
            return False

        if lobby.lobby_type == "single":
            return len(lobby.players) == 1

        if len(lobby.players) < 2:
            return False

        return all(lobby.ready_status.get(player_id, False) for player_id in lobby.players)

    def start_game(self, lobby_id: int, host_id: str) -> dict:
        if not self.can_start_game(lobby_id, host_id):
            raise ValueError("Game cannot start yet")

        lobby = self._get_lobby(lobby_id)
        lobby.is_open = False

        return {
            "message": "Game started",
            "lobby_id": lobby.lobby_id,
            "players": lobby.players
        }

    def lobby_to_dict(self, lobby: Lobby) -> dict:
        return {
            "lobby_id": lobby.lobby_id,
            "name": lobby.name,
            "lobby_type": lobby.lobby_type,
            "host_id": lobby.host_id,
            "max_players": lobby.max_players,
            "invite_code": lobby.invite_code,
            "players": lobby.players,
            "ready_status": lobby.ready_status,
            "is_open": lobby.is_open
        }

    def _get_lobby(self, lobby_id: int) -> Lobby:
        if lobby_id not in self.lobbies:
            raise ValueError("Lobby not found")

        return self.lobbies[lobby_id]

    def _generate_invite_code(self) -> str:
        return "".join(random.choices(string.ascii_uppercase + string.digits, k=8))