from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

from .engine import GameState, GameEngine

# result struct for game summary
@dataclass
class StreamResult:
    winner_id: Optional[str]
    rounds_played: int
    events: List[dict]


class SinglePlayerGameStream:
    """Single-player stream controller.

    This stream assumes one human player plus configurable AI players.
    """

    def __init__(
        self,
        engine: GameEngine,
        human_player_id: str,
        human_name: str = "You",
        ai_count: int = 3,
    ):
        self.engine = engine
        players = [{"player_id": human_player_id, "name": human_name}]
        players.extend(
            {"player_id": f"ai_{i+1}", "name": f"AI {i+1}"}
            for i in range(max(1, ai_count))
        )
        self.state = self.engine.initialize_game(players)
        self.human_player_id = human_player_id

    def run(
        self,
        human_decision_provider: Callable[[str, str, dict], dict],
        max_rounds: int = 500,
    ) -> StreamResult:
        events: List[dict] = []
        rounds = 0

        while not self.state.winner_id and rounds < max_rounds:
            current = self.state.turn_order[self.state.current_turn_index]
            if current == self.human_player_id:
                provider = human_decision_provider
            else:
                provider = self._ai_decision_provider

            event = self.engine.take_turn(self.state, provider)
            events.append(event)
            rounds += 1

        return StreamResult(
            winner_id=self.state.winner_id,
            rounds_played=rounds,
            events=events,
        )

    def _ai_decision_provider(self, player_id: str, action: str, context: dict) -> dict:
        player = self.state.players[player_id]

        if action == "buy_property":
            price = int(context["buy_price"])
            # AI buys if it can still keep a cash safety buffer.
            return {"buy": player.cash - price >= 150}

        if action == "auction_bid":
            current_bid = int(context["current_bid"])
            minimum_raise = int(context["minimum_raise"])
            buy_price = int(context["buy_price"])
            next_bid = current_bid + minimum_raise

            soft_cap = int(buy_price * 1.25)
            can_bid = next_bid <= player.cash and next_bid <= soft_cap
            return {"bid": can_bid, "amount": next_bid}

        if action == "jail_action":
            has_card = bool(context.get("has_card"))
            sellers = context.get("sellers", [])
            if has_card:
                return {"choice": "use_card"}
            if sellers and player.cash >= 200:
                return {"choice": "buy_card"}
            return {"choice": "roll"}

        if action == "jail_buy_offer":
            sellers = context.get("sellers")
            seller_id = None
            if isinstance(sellers, list) and sellers:
                seller_id = sellers[0]
            offer = 75 if player.cash >= 200 else 50
            return {"seller_id": seller_id, "offer": offer}

        if action == "jail_buy_response":
            offer = int(context.get("offer", 0))
            return {"accept": offer >= 75}

        return {}


class MultiPlayerGameStream:
    """Multiplayer stream controller for lobby-backed sessions.

    The decision provider is expected to route action requests to each connected player.
    """

    def __init__(self, engine: GameEngine, players: List[Dict[str, str]]):
        if len(players) < 2:
            raise ValueError("Multiplayer stream requires at least 2 players")
        self.engine = engine
        self.state: GameState = self.engine.initialize_game(players)

    def step(self, decision_provider: Callable[[str, str, dict], dict]) -> dict:
        return self.engine.take_turn(self.state, decision_provider)

    def run_until_end(
        self,
        decision_provider: Callable[[str, str, dict], dict],
        max_rounds: int = 1000,
    ) -> StreamResult:
        rounds = 0
        events: List[dict] = []

        while not self.state.winner_id and rounds < max_rounds:
            events.append(self.step(decision_provider))
            rounds += 1

        return StreamResult(
            winner_id=self.state.winner_id,
            rounds_played=rounds,
            events=events,
        )
