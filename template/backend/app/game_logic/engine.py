from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional

# JSON Structures for game configuration and state
# Data stored in ./monopoly_state.json

@dataclass
class TileDef:
    index: int
    tile_type: str
    name: str
    color_group: Optional[str]
    buy_price: int
    base_rent: int
    house_cost: int
    house_rents: List[int]
    hotel_rent: int


@dataclass
class EventCard:
    card_id: str
    description: str
    action: str
    amount: int = 0
    destination: Optional[int] = None
    weight: float = 0


@dataclass
class GameConfig:
    start_cash: int
    go_salary: int
    jail_fine: int
    max_houses_per_property: int
    tiles: List[TileDef]
    chance_cards: List[EventCard]
    treasure_cards: List[EventCard]


@dataclass
class PropertyState:
    owner_id: Optional[str] = None
    houses: int = 0
    has_hotel: bool = False
    mortgaged: bool = False


@dataclass
class PlayerState:
    player_id: str
    name: str
    cash: int
    pos: int = 0
    in_jail_turns: int = 0
    jail_cards: int = 0
    bankrupt: bool = False
    consecutive_doubles: int = 0
    turns_taken: int = 0


@dataclass
class GameState:
    players: Dict[str, PlayerState]
    properties: Dict[int, PropertyState]
    turn_order: List[str]
    current_turn_index: int = 0
    winner_id: Optional[str] = None

# utility function for loading game configuration
def load_game_config(config_path: str) -> GameConfig:
    data = json.loads(Path(config_path).read_text(encoding="utf-8"))

    tiles = [
        TileDef(
            index=t["index"],
            tile_type=t["tile_type"],
            name=t["name"],
            color_group=t.get("color_group"),
            buy_price=t.get("buy_price", 0),
            base_rent=t.get("rent", 0),
            house_cost=t.get("house_cost", 0),
            house_rents=t.get("house_rents", []),
            hotel_rent=t.get("hotel_rent", 0),
        )
        for t in data["tiles"]
    ]

    chance_cards = [
        EventCard(
            card_id=c["id"],
            description=c["description"],
            action=c["action"],
            amount=c.get("amount", 0),
            destination=c.get("destination"),
            weight = c.get("weight")
        )
        for c in data["chance_events"]
    ]

    treasure_cards = [
        EventCard(
            card_id=c["id"],
            description=c["description"],
            action=c["action"],
            amount=c.get("amount", 0),
            destination=c.get("destination"),
            weight=c.get("weight")
        )
        for c in data["treasure_events"]
    ]

    settings = data["settings"]
    return GameConfig(
        start_cash=settings["start_cash"],
        go_salary=settings["go_salary"],
        jail_fine=settings["jail_fine"],
        max_houses_per_property=settings["max_houses_per_property"],
        tiles=tiles,
        chance_cards=chance_cards,
        treasure_cards=treasure_cards,
    )

# Main game engine class
class GameEngine:


    #initialize game state with config and random seed
    def __init__(self, config: GameConfig, seed: Optional[int] = None):
        self.config = config
        self.random = random.Random(seed)
        self.chance_deck = list(config.chance_cards)
        self.treasure_deck = list(config.treasure_cards)
        self.random.shuffle(self.chance_deck)
        self.random.shuffle(self.treasure_deck)


    #initialize game state with list of players, return initial GameState
    def initialize_game(self, players: List[Dict[str, str]]) -> GameState:
        player_states = {
            p["player_id"]: PlayerState(
                player_id=p["player_id"],
                name=p["name"],
                cash=self.config.start_cash,
            )
            for p in players
        }

        properties = {
            tile.index: PropertyState()
            for tile in self.config.tiles
            if tile.tile_type == "property"
        }

        return GameState(
            players=player_states,
            properties=properties,
            turn_order=[p["player_id"] for p in players],
        )

    # dice roller
    def roll_dice_pair(self) -> tuple[int, int]:
        return self.random.randint(1, 6), self.random.randint(1, 6)

    def roll_dice(self) -> int:
        d1, d2 = self.roll_dice_pair()
        return d1 + d2

    # turn logic flow, return events happened as dict
    def take_turn(
        self,
        state: GameState,
        decision_provider: Callable[[str, str, dict], dict],
    ) -> dict:
        player_id = state.turn_order[state.current_turn_index]
        player = state.players[player_id]

        if player.bankrupt:
            self._advance_turn(state)
            return {"type": "skip_bankrupt", "player_id": player_id}

        player.turns_taken += 1

        jail_event: Optional[dict] = None
        dice_total: Optional[int] = None
        rolled_double = False

        if player.in_jail_turns > 0:
            jail_event, can_continue, dice_total, rolled_double = self._handle_jail_turn(
                state,
                player_id,
                decision_provider,
            )
            if not can_continue:
                self._check_winner(state)
                self._advance_turn(state)
                return jail_event
        else:
            d1, d2 = self.roll_dice_pair()
            dice_total = d1 + d2
            rolled_double = d1 == d2

            if rolled_double:
                player.consecutive_doubles += 1
            else:
                player.consecutive_doubles = 0

            if player.consecutive_doubles >= 3:
                self._send_to_jail(player)
                event = {
                    "type": "go_to_jail_double",
                    "player_id": player_id,
                    "roll": dice_total,
                }
                self._check_winner(state)
                self._advance_turn(state)
                return event

        if dice_total is None:
            d1, d2 = self.roll_dice_pair()
            dice_total = d1 + d2
            rolled_double = d1 == d2

        move = dice_total
        old_pos = player.pos
        new_pos = (old_pos + move) % len(self.config.tiles)
        player.pos = new_pos
        if new_pos < old_pos:
            player.cash += self.config.go_salary

        tile = self.config.tiles[new_pos]
        event = self._resolve_tile(state, player_id, tile, decision_provider)
        event.setdefault("roll", move)
        event.setdefault("rolled_double", rolled_double)

        if jail_event:
            event = {
                "type": "jail_release",
                "player_id": player_id,
                "jail_event": jail_event,
                "tile_event": event,
                "roll": move,
            }

        self._check_winner(state)
        self._advance_turn(state)
        return event


    # return dict defining tile behaviour and player decision
    def _resolve_tile(
        self,
        state: GameState,
        player_id: str,
        tile: TileDef,
        decision_provider: Callable[[str, str, dict], dict],
    ) -> dict:
        player = state.players[player_id]
        
        #handle property tile: buy, rent, or auction
        if tile.tile_type == "property":
            p_state = state.properties[tile.index]
            if p_state.owner_id is None:
                decision = decision_provider(
                    player_id,
                    "buy_property",
                    {"tile_index": tile.index, "buy_price": tile.buy_price, "name": tile.name},
                )
                wants_buy = bool(decision.get("buy", False))    # initiate buy decision, default to False if not provided or invalid
                if wants_buy and player.cash >= tile.buy_price:
                    player.cash -= tile.buy_price
                    p_state.owner_id = player_id
                    return {"type": "property_bought", "player_id": player_id, "tile": tile.name}

                auction_result = self.run_property_auction(state, tile, decision_provider)
                return {"type": "auction", "tile": tile.name, "result": auction_result}

            # process rent payment if landing on owned property
            if p_state.owner_id != player_id:
                rent = self._calculate_rent(tile, p_state)
                paid = self._charge_player(state, player_id, rent, creditor_id=p_state.owner_id)
                return {
                    "type": "rent_paid",
                    "from": player_id,
                    "to": p_state.owner_id,
                    "amount": paid["paid_amount"],
                    "required_amount": rent,
                    "tile": tile.name,
                    "bankrupt": paid["bankrupt"],
                }

            return {"type": "landed_own_property", "player_id": player_id, "tile": tile.name}

        #chance tile - return chance event and apply effect
        if tile.tile_type == "chance":
            return self._draw_card(state, player_id, "chance")

        # treasure tile - return treasure event and apply effect
        if tile.tile_type == "treasure":
            return self._draw_card(state, player_id, "treasure")

        # tax tile - pay tax amount. If the player cannot raise enough cash,
        # they are declared bankrupt and removed from the game.
        if tile.tile_type == "tax":
            paid = self._charge_player(state, player_id, tile.base_rent)
            return {
                "type": "tax_paid",
                "player_id": player_id,
                "amount": paid["paid_amount"],
                "required_amount": tile.base_rent,
                "bankrupt": paid["bankrupt"],
            }

        # Go To Jail must move the player directly to Jail and end their turn.
        if tile.tile_type == "go_to_jail":
            self._send_to_jail(player)
            return {"type": "go_to_jail", "player_id": player_id, "tile": tile.name}

        return {"type": "no_action", "player_id": player_id, "tile": tile.name}


    #handle property auction when property is passed without purchase
    def run_property_auction(
        self,
        state: GameState,
        tile: TileDef,
        decision_provider: Callable[[str, str, dict], dict],
    ) -> dict:
        participants = [p for p in state.turn_order if not state.players[p].bankrupt]
        current_bid = 0
        leading_bidder: Optional[str] = None
        active = set(participants)

        while len(active) > 1:
            for bidder_id in list(active):
                if len(active) <= 1:
                    break

                increment = self._auction_increment(tile.buy_price, current_bid)
                decision = decision_provider(
                    bidder_id,
                    "auction_bid",
                    {
                        "tile_index": tile.index,
                        "tile_name": tile.name,
                        "current_bid": current_bid,
                        "minimum_raise": increment,
                        "buy_price": tile.buy_price,
                    },
                )

                if not decision.get("bid", False):
                    active.discard(bidder_id)
                    continue

                proposed = int(decision.get("amount", current_bid + increment))
                min_required = current_bid + increment
                if proposed < min_required:
                    proposed = min_required

                bidder = state.players[bidder_id]
                if proposed > bidder.cash:
                    active.discard(bidder_id)
                    continue

                current_bid = proposed
                leading_bidder = bidder_id

            if current_bid == 0:
                break

        if leading_bidder is None:
            return {"winner": None, "amount": 0}

        winner = state.players[leading_bidder]
        winner.cash -= current_bid
        p_state = state.properties[tile.index]
        p_state.owner_id = leading_bidder
        return {"winner": leading_bidder, "amount": current_bid}

    # increase bid amount, curved with current bid price
    def _auction_increment(self, price: int, current_bid: int) -> int:
        base = max(5, int(round((price * 0.05) / 5.0) * 5))
        if current_bid >= int(price * 1.5):
            return base * 3
        if current_bid >= price:
            return base * 2
        return base

    # return property rent based on property state
    def _calculate_rent(self, tile: TileDef, state: PropertyState) -> int:
        if state.mortgaged:
            return 0  # Mortgaged properties generate no rent
        if state.has_hotel:
            return tile.hotel_rent
        if state.houses > 0 and state.houses <= len(tile.house_rents):
            return tile.house_rents[state.houses - 1]
        return tile.base_rent

    # return event card
    def _draw_card(self, state: GameState, player_id: str, deck_type: str) -> dict:
        player = state.players[player_id]
        deck = self.chance_deck if deck_type == "chance" else self.treasure_deck
        if not deck:
            return {"type": "card_none", "deck": deck_type}

        card = deck.pop(0)
        deck.append(card)

        if card.action == "money":
            player.cash += card.amount
        elif card.action == "move" and card.destination is not None:
            old = player.pos
            player.pos = card.destination
            if card.destination < old:
                player.cash += self.config.go_salary
        elif card.action == "jail":
            player.pos = self._find_tile_index("Jail")
            player.in_jail_turns = 1
        elif card.action == "get_out_of_jail":
            if player.jail_cards >= 1:
                player.cash += 25
                player.jail_cards = 1 # reset invalid values back to 1
            else:
                player.jail_cards = 1

        return {
            "type": "card_drawn",
            "deck": deck_type,
            "card_id": card.card_id,
            "description": card.description,
        }

    def _handle_jail_turn(
        self,
        state: GameState,
        player_id: str,
        decision_provider: Callable[[str, str, dict], dict],
    ) -> tuple[dict, bool, Optional[int], bool]:
        player = state.players[player_id]
        sellers = [
            pid for pid, p in state.players.items()
            if pid != player_id and p.jail_cards > 0 and not p.bankrupt
        ]

        if player.in_jail_turns >= 3:
            paid = self._charge_player(state, player_id, self.config.jail_fine)
            player.in_jail_turns = 0
            player.consecutive_doubles = 0
            return {
                "type": "jail_forced_release",
                "player_id": player_id,
                "fine": self.config.jail_fine,
                "amount": paid["paid_amount"],
                "bankrupt": paid["bankrupt"],
            }, not paid["bankrupt"], None, False

        decision = decision_provider(
            player_id,
            "jail_action",
            {
                "has_card": player.jail_cards > 0,
                "sellers": sellers,
                "turns_in_jail": player.in_jail_turns,
                "fine": self.config.jail_fine,
            },
        )
        choice = str(decision.get("choice", "roll")).lower()

        if choice in {"pay", "pay_fine", "fine"}:
            paid = self._charge_player(state, player_id, self.config.jail_fine)
            player.in_jail_turns = 0
            player.consecutive_doubles = 0
            return {
                "type": "jail_paid_fine",
                "player_id": player_id,
                "fine": self.config.jail_fine,
                "amount": paid["paid_amount"],
                "bankrupt": paid["bankrupt"],
            }, not paid["bankrupt"], None, False

        if choice == "use_card" and player.jail_cards > 0:
            player.jail_cards -= 1
            player.in_jail_turns = 0
            player.consecutive_doubles = 0
            return {"type": "jail_used_card", "player_id": player_id}, True, None, False

        if choice == "buy_card" and sellers:
            result = self._negotiate_jail_card_purchase(
                state,
                player_id,
                sellers,
                decision_provider,
            )
            if result.get("success"):
                player.in_jail_turns = 0
                player.consecutive_doubles = 0
                return {
                    "type": "jail_bought_card",
                    "player_id": player_id,
                    "negotiation": result,
                }, True, None, False

            player.in_jail_turns += 1
            return {
                "type": "jail_buy_failed",
                "player_id": player_id,
                "negotiation": result,
            }, False, None, False

        d1, d2 = self.roll_dice_pair()
        rolled_double = d1 == d2
        if rolled_double:
            player.in_jail_turns = 0
            player.consecutive_doubles = 0
            return {
                "type": "jail_roll_doubles",
                "player_id": player_id,
                "roll": d1 + d2,
            }, True, d1 + d2, True

        player.in_jail_turns += 1
        player.consecutive_doubles = 0
        return {
            "type": "jail_roll_failed",
            "player_id": player_id,
            "roll": d1 + d2,
        }, False, None, False

    def _negotiate_jail_card_purchase(
        self,
        state: GameState,
        buyer_id: str,
        sellers: List[str],
        decision_provider: Callable[[str, str, dict], dict],
    ) -> dict:
        seller_id = decision_provider(
            buyer_id,
            "jail_buy_offer",
            {"round": 1, "sellers": sellers},
        ).get("seller_id")

        if seller_id not in sellers:
            seller_id = sellers[0]

        for round_idx in range(1, 4):
            offer = decision_provider(
                buyer_id,
                "jail_buy_offer",
                {"round": round_idx, "seller_id": seller_id},
            ).get("offer", 0)

            try:
                offer_value = int(offer)
            except (TypeError, ValueError):
                offer_value = 0

            seller_decision = decision_provider(
                seller_id,
                "jail_buy_response",
                {"round": round_idx, "buyer_id": buyer_id, "offer": offer_value},
            )
            accepted = bool(seller_decision.get("accept", False))

            if accepted and offer_value > 0:
                buyer = state.players[buyer_id]
                seller = state.players[seller_id]
                if buyer.cash >= offer_value and seller.jail_cards > 0:
                    buyer.cash -= offer_value
                    seller.cash += offer_value
                    seller.jail_cards -= 1
                    return {
                        "success": True,
                        "seller_id": seller_id,
                        "price": offer_value,
                        "round": round_idx,
                    }

        return {"success": False, "seller_id": seller_id}

    def _find_tile_index(self, name: str) -> int:
        for tile in self.config.tiles:
            if tile.name == name:
                return tile.index
        return 0

    def _send_to_jail(self, player: PlayerState) -> None:
        player.pos = self._find_tile_index("Jail")
        player.in_jail_turns = 1
        player.consecutive_doubles = 0

    def _charge_player(
        self,
        state: GameState,
        player_id: str,
        amount: int,
        creditor_id: Optional[str] = None,
    ) -> dict:
        """Charge a player and automatically liquidate assets if needed.

        Bankruptcy rule implemented here:
        a player is bankrupt only when they cannot pay a required rent,
        tax, or fine even after selling all houses and mortgaging/selling
        all properties for their liquidation value.
        """
        player = state.players[player_id]
        amount = max(0, int(amount or 0))

        if amount == 0 or player.bankrupt:
            return {"paid_amount": 0, "bankrupt": player.bankrupt}

        if player.cash < amount:
            self._liquidate_assets_until_cash_available(state, player_id, amount)

        paid_amount = min(player.cash, amount)
        player.cash -= paid_amount

        if creditor_id and creditor_id in state.players and not state.players[creditor_id].bankrupt:
            state.players[creditor_id].cash += paid_amount

        if paid_amount < amount:
            self._declare_bankrupt(state, player_id)
            return {"paid_amount": paid_amount, "bankrupt": True}

        return {"paid_amount": paid_amount, "bankrupt": False}

    def _liquidate_assets_until_cash_available(
        self,
        state: GameState,
        player_id: str,
        target_cash: int,
    ) -> None:
        player = state.players[player_id]
        player_properties = [
            (idx, p_state, self.config.tiles[idx])
            for idx, p_state in state.properties.items()
            if p_state.owner_id == player_id
        ]

        # Sell buildings first because a player must remove houses before
        # disposing of the land itself.
        for tile_index, p_state, tile in player_properties:
            while p_state.houses > 0 and player.cash < target_cash:
                p_state.houses -= 1
                player.cash += max(1, tile.house_cost // 2)

            if p_state.has_hotel and player.cash < target_cash:
                p_state.has_hotel = False
                player.cash += max(1, tile.house_cost // 2)

        # Then sell/mortgage properties for half of purchase price. The
        # property returns to the bank, so bankrupt/exited players do not
        # keep assets on the board.
        for tile_index, p_state, tile in player_properties:
            if player.cash >= target_cash:
                break
            if p_state.owner_id == player_id:
                player.cash += max(1, tile.buy_price // 2)
                p_state.owner_id = None
                p_state.houses = 0
                p_state.has_hotel = False
                p_state.mortgaged = False

    def _declare_bankrupt(self, state: GameState, player_id: str) -> None:
        player = state.players[player_id]
        player.bankrupt = True
        player.cash = 0
        player.in_jail_turns = 0
        player.consecutive_doubles = 0

        for p_state in state.properties.values():
            if p_state.owner_id == player_id:
                p_state.owner_id = None
                p_state.houses = 0
                p_state.has_hotel = False
                p_state.mortgaged = False

    def _check_winner(self, state: GameState) -> None:
        active = [p.player_id for p in state.players.values() if not p.bankrupt]
        if len(active) == 1:
            state.winner_id = active[0]

    def _advance_turn(self, state: GameState) -> None:
        if not state.turn_order:
            return
        state.current_turn_index = (state.current_turn_index + 1) % len(state.turn_order)
