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
    def roll_dice(self) -> int:
        return self.random.randint(1, 6) + self.random.randint(1, 6)

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

        jail_event: Optional[dict] = None
        jail_roll_total: Optional[int] = None
        if player.in_jail_turns > 0:
            jail_event, can_continue, jail_roll_total = self._handle_jail_turn(
                state,
                player_id,
                decision_provider,
            )
            if not can_continue:
                self._check_bankruptcy(state, player_id)
                self._check_winner(state)
                self._advance_turn(state)
                return jail_event

        if jail_roll_total is None:
            d1, d2 = self.roll_dice(), self.roll_dice()
            double_jail = 0
            move = 0
            while d1 == d2 and double_jail != 3:
                double_jail += 1
                move += d1 + d2
                d1, d2 = self.roll_dice(), self.roll_dice()
            if double_jail == 3:
                # teleport player to jail tile
                player.pos = self._find_tile_index("Jail")
                player.in_jail_turns = 1
                event = {"type": "go_to_jail_double", "player_id": player_id}
                self._check_bankruptcy(state, player_id)
                self._check_winner(state)
                self._advance_turn(state)
                return event
        else:
            move = jail_roll_total
        
        old_pos = player.pos
        new_pos = (old_pos + move) % len(self.config.tiles)
        player.pos = new_pos
        if new_pos < old_pos:
            player.cash += self.config.go_salary

        tile = self.config.tiles[new_pos]
        event = self._resolve_tile(state, player_id, tile, decision_provider)
        if jail_event:
            event = {
                "type": "jail_release",
                "player_id": player_id,
                "jail_event": jail_event,
                "tile_event": event,
            }

        self._check_bankruptcy(state, player_id)
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
                owner = state.players[p_state.owner_id]
                player.cash -= rent
                owner.cash += rent
                return {
                    "type": "rent_paid",
                    "from": player_id,
                    "to": p_state.owner_id,
                    "amount": rent,
                    "tile": tile.name,
                }

            return {"type": "landed_own_property", "player_id": player_id, "tile": tile.name}

        #chance tile - return chance event and apply effect
        if tile.tile_type == "chance":
            return self._draw_card(state, player_id, "chance")

        # treasure tile - return treasure event and apply effect
        if tile.tile_type == "treasure":
            return self._draw_card(state, player_id, "treasure")

        # tax tile - pay tax amount (mfw ATO)
        if tile.tile_type == "tax":
            player.cash -= tile.base_rent
            return {"type": "tax_paid", "player_id": player_id, "amount": tile.base_rent}

        # go to jail tile - no effect when player pass
        if tile.tile_type == "go_to_jail":
            pass # free parking
        return {"type": "no_action", "tile": tile.name}


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
    ) -> tuple[dict, bool, Optional[int]]:
        player = state.players[player_id]
        sellers = [
            pid for pid, p in state.players.items()
            if pid != player_id and p.jail_cards > 0 and not p.bankrupt
        ]

        if player.in_jail_turns >= 3:
            player.cash -= self.config.jail_fine
            player.in_jail_turns = 0
            return {
                "type": "jail_forced_release",
                "player_id": player_id,
                "fine": self.config.jail_fine,
            }, True, None

        decision = decision_provider(
            player_id,
            "jail_action",
            {
                "has_card": player.jail_cards > 0,
                "sellers": sellers,
                "turns_in_jail": player.in_jail_turns,
            },
        )
        choice = str(decision.get("choice", "roll")).lower()

        if choice == "use_card" and player.jail_cards > 0:
            player.jail_cards -= 1
            player.in_jail_turns = 0
            return {"type": "jail_used_card", "player_id": player_id}, True, None

        if choice == "buy_card" and sellers:
            result = self._negotiate_jail_card_purchase(
                state,
                player_id,
                sellers,
                decision_provider,
            )
            if result.get("success"):
                player.jail_cards += 1
                player.jail_cards -= 1
                player.in_jail_turns = 0
                return {
                    "type": "jail_bought_card",
                    "player_id": player_id,
                    "negotiation": result,
                }, True, None

            player.in_jail_turns += 1
            return {
                "type": "jail_buy_failed",
                "player_id": player_id,
                "negotiation": result,
            }, False, None

        d1, d2 = self.roll_dice(), self.roll_dice()
        if d1 == d2:
            player.in_jail_turns = 0
            return {
                "type": "jail_roll_doubles",
                "player_id": player_id,
                "roll": d1 + d2,
            }, True, d1 + d2

        player.in_jail_turns += 1
        return {
            "type": "jail_roll_failed",
            "player_id": player_id,
            "roll": d1 + d2,
        }, False, None

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

    def _check_bankruptcy(self, state: GameState, player_id: str) -> None:
        """Check and potentially declare bankruptcy.
        
        Players only go bankrupt if their net worth (cash + property value)
        is insufficient to cover their debt. They may liquidate mortgages first.
        """
        player = state.players[player_id]
        if player.cash >= 0:
            return 
        
        # Calculate net worth (cash + unmortgaged properties)
        net_worth = self._get_player_net_worth(state, player_id)
        
        # If net worth is sufficient, liquidate mortgages to cover debt
        if net_worth >= abs(player.cash):
            self._liquidate_mortgages(state, player_id, abs(player.cash))
            return
        
        # Player is bankrupt: lose all properties and assets
        player.bankrupt = True
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

    def _get_player_net_worth(self, state: GameState, player_id: str) -> int:
        """Calculate player's net worth: cash + unmortgaged property value.
        
        Unmortgaged properties are valued at 50% of their purchase price
        (standard mortgage value in Monopoly).
        """
        player_cash = state.players[player_id].cash
        property_value = 0
        
        for tile_index, p_state in state.properties.items():
            if p_state.owner_id == player_id and not p_state.mortgaged:
                tile = self.config.tiles[tile_index]
                # Property value is 50% of purchase price (standard mortgage value)
                property_value += tile.buy_price // 2
        
        return player_cash + property_value
    
    def _liquidate_mortgages(self, state: GameState, player_id: str, amount_needed: int) -> None:
        """Force-sell assets to raise cash for debt payment.
        
        Liquidation order (highest rent properties first):
        1. Sell hotels individually (50% of house cost, since hotel replaces 4 houses)
        2. Sell houses individually (50% of house cost)
        3. Mortgage unmortgaged properties (50% of property purchase price)
        """
        player = state.players[player_id]
        amount_raised = 0
        
        # Get all player's properties sorted by rent (highest first)
        player_properties = [
            (idx, p_state, self.config.tiles[idx])
            for idx, p_state in state.properties.items()
            if p_state.owner_id == player_id
        ]
        player_properties.sort(
            key=lambda x: x[2].base_rent,
            reverse=True
        )
        
        # Sell hotels
        for tile_index, p_state, tile in player_properties:
            if amount_raised >= amount_needed:
                break
            
            if p_state.has_hotel and amount_raised < amount_needed:
                hotel_value = tile.house_cost // 2  # Hotel worth same as single house
                p_state.has_hotel = False
                player.cash += hotel_value
                amount_raised += hotel_value

        # Sell houses
        for tile_index, p_state, tile in player_properties:
            if amount_raised >= amount_needed:
                break
            
            while p_state.houses > 0 and amount_raised < amount_needed:
                house_value = tile.house_cost // 2
                p_state.houses -= 1
                player.cash += house_value
                amount_raised += house_value
        
        # Phase 3: Mortgage properties
        for tile_index, p_state, tile in player_properties:
            if amount_raised >= amount_needed:
                break
            
            if not p_state.mortgaged and p_state.houses == 0 and not p_state.has_hotel:
                mortgage_value = tile.buy_price // 2
                p_state.mortgaged = True
                player.cash += mortgage_value
                amount_raised += mortgage_value
    
    def _advance_turn(self, state: GameState) -> None:
        if not state.turn_order:
            return
        state.current_turn_index = (state.current_turn_index + 1) % len(state.turn_order)
