import asyncio
import uuid
import sys
import os
from typing import Dict, Any, List

from .models import Message, NodeConfig
from .state import StateManager
from .network import NetworkManager
from .protocols.token import TokenProtocol
from .protocols.mutex import MutexProtocol
from .protocols.snapshot import SnapshotProtocol
from .utils import log_debug, is_valid_play, card_label

class Node:
    def __init__(self, config: NodeConfig):
        self.config = config
        self.state = StateManager(config.node_id)
        self.network = NetworkManager(config, self.handle_peer_message)
        
        self.token_proto = TokenProtocol(config.node_id, self.state, self.network)
        self.mutex_proto = MutexProtocol(config.node_id, self.state, self.network)
        self.snapshot_proto = SnapshotProtocol(config.node_id, self.state, self.network)
        
        if config.is_initial_token_holder:
            self.state.has_token = True

    async def start(self):
        await self.network.connect_to_peers()
        await self.token_proto.start()

    async def handle_peer_message(self, msg: Message):
        await self.state.update_ts(msg.ts)
        
        if msg.type != "MARKER":
            self.snapshot_proto.record_message(msg)

        if msg.type == "TOKEN":
            await self.token_proto.handle_token(msg)
        elif msg.type == "MUTEX_REQUEST":
            await self.mutex_proto.handle_request(msg)
        elif msg.type == "MUTEX_REPLY":
            await self.mutex_proto.handle_reply(msg)
        elif msg.type == "MARKER":
            await self.snapshot_proto.handle_marker(msg)
        elif msg.type == "SNAPSHOT_STATE":
            await self.snapshot_proto.handle_snapshot_state(msg)
        elif msg.type == "GAME_ACTION":
            await self.handle_game_action(msg)
        
        await self.network.notify_ui(self.state.to_ui_dict())

    async def handle_game_action(self, msg: Message):
        action = msg.payload.get("action")
        if action == "PLAY_CARD":
            pile_idx = msg.payload["pile_idx"]
            card = msg.payload["card"]
            self.state.center_piles[pile_idx].append(card)
            self.state.add_log("game", f"Player {msg.src} played {card_label(card)} to pile {pile_idx + 1}")
        elif action == "RESET_PILES":
            from .state import build_deck
            tmp = build_deck()
            self.state.center_piles = [[tmp.pop()], [tmp.pop()]]
            self.state.winner = None  # Reset winner on pile reset
            self.state.add_log("game", f"Center piles reset by {msg.src}")
        elif action == "PLAYER_WON":
            winner_id = msg.payload["winner"]
            self.state.winner = winner_id
            self.state.add_log("game", f"🏆 {winner_id} has WON the game by emptying their hand!")

    async def ui_play_card(self, pile_idx: int, card: dict):
        """
        Play a card from hand onto a center pile.
        On success the card is removed from hand — NO auto-draw.
        Win condition: if hand becomes empty after playing, broadcast PLAYER_WON.
        """
        if self.state.winner:
            return False  # Game already over

        # 0. Must be in hand
        matching = [c for c in self.state.hand if c["rank"] == card["rank"] and c["suit"] == card["suit"]]
        if not matching:
            self.state.add_log("game", f"Card {card_label(card)} not in hand")
            return False

        # 1. Validity check (rank ±1, A↔K wrap; suit ignored)
        top_card = self.state.center_piles[pile_idx][-1]
        if not is_valid_play(top_card, card):
            self.state.add_log("game", f"Invalid play: {card_label(card)} on {card_label(top_card)}")
            return False

        # 2. Request distributed mutex
        self.state.mutex_event.clear()
        await self.mutex_proto.request_access()
        try:
            await asyncio.wait_for(self.state.mutex_event.wait(), timeout=5.0)
        except asyncio.TimeoutError:
            self.state.add_log("mutex", "Failed to acquire mutex (timeout)")
            if self.state.mutex_state == "WANTED":
                self.state.mutex_state = "RELEASED"
                # Clear state to allow future requests
                self.state.mutex_replies_received.clear()
            return False

        if self.state.mutex_state != "HELD":
            return False

        # 3. Re-check after acquiring mutex
        top_card = self.state.center_piles[pile_idx][-1]
        if not is_valid_play(top_card, card):
            self.state.add_log("game", "Pile changed during mutex wait — play no longer valid")
            await self.mutex_proto.release()
            return False

        # 4. Commit: remove card from hand, push onto center pile
        self.state.hand.remove(matching[0])
        self.state.center_piles[pile_idx].append(card)
        self.state.add_log(
            "game",
            f"I played {card_label(card)} → pile {pile_idx + 1}. Hand: {len(self.state.hand)} cards"
        )

        # 5. Broadcast the play to peers
        play_msg = Message(
            type="GAME_ACTION",
            src=self.config.node_id,
            dst="all",
            id=str(uuid.uuid4()),
            ts=await self.state.get_next_ts(),
            payload={"action": "PLAY_CARD", "pile_idx": pile_idx, "card": card}
        )
        await self.network.broadcast(play_msg)

        # 6. Win check — empty hand means this player wins
        if len(self.state.hand) == 0:
            self.state.winner = self.config.node_id
            self.state.add_log("game", f"🏆 I WON! Hand is empty!")
            win_msg = Message(
                type="GAME_ACTION",
                src=self.config.node_id,
                dst="all",
                id=str(uuid.uuid4()),
                ts=await self.state.get_next_ts(),
                payload={"action": "PLAYER_WON", "winner": self.config.node_id}
            )
            await self.network.broadcast(win_msg)

        # 7. Release mutex
        await self.mutex_proto.release()
        return True

    async def ui_draw_card(self):
        """
        Draw one card from the private face-down deck.
        SMART DRAW: prefer a card that is immediately playable on one of the current
        center pile tops — this increases the player's chance of winning.
        If no playable card exists in deck, fall back to a random draw.
        """
        if self.state.winner:
            return False
        if not self.state.deck:
            self.state.add_log("game", "Draw deck is empty")
            return False

        # Collect the top rank of each center pile (for playability check)
        pile_tops = [pile[-1] for pile in self.state.center_piles]

        # Search deck for a card playable on any center pile
        playable_idx = None
        for i, deck_card in enumerate(self.state.deck):
            if any(is_valid_play(top, deck_card) for top in pile_tops):
                playable_idx = i
                break  # Take the first playable card found

        if playable_idx is not None:
            drawn = self.state.deck.pop(playable_idx)
            self.state.add_log(
                "game",
                f"Drew {card_label(drawn)} (playable!). Hand: {len(self.state.hand)} cards, Deck: {len(self.state.deck)} left"
            )
        else:
            # No playable card in deck — draw random (pop from end of shuffled deck)
            drawn = self.state.deck.pop()
            self.state.add_log(
                "game",
                f"Drew {card_label(drawn)}. Hand: {len(self.state.hand)} cards, Deck: {len(self.state.deck)} left"
            )

        self.state.hand.append(drawn)
        return True

    async def ui_shuffle_deck(self):
        """Reset center piles (requires TOKEN)."""
        if await self.token_proto.use_token_for_action("Reset Center Piles"):
            from .state import build_deck
            tmp = build_deck()
            self.state.center_piles = [[tmp.pop()], [tmp.pop()]]
            self.state.winner = None
            self.state.add_log("game", "Center piles reset via Token")
            
            msg = Message(
                type="GAME_ACTION",
                src=self.config.node_id,
                dst="all",
                id=str(uuid.uuid4()),
                ts=await self.state.get_next_ts(),
                payload={"action": "RESET_PILES"}
            )
            await self.network.broadcast(msg)
            return True
        return False
