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
        
        self.token_proto = TokenProtocol(config.node_id, self.state, self.network, self.broadcast_log)
        self.mutex_proto = MutexProtocol(config.node_id, self.state, self.network)
        self.snapshot_proto = SnapshotProtocol(config.node_id, self.state, self.network)
        
        self.token_timeout_task: Optional[asyncio.Task] = None

    async def start(self):
        await self.network.connect_to_peers()
        await self.token_proto.start()
        
        # DESIGNATED LEADER: The person who is initial token holder handles Game Start
        if self.config.is_initial_token_holder:
            await asyncio.sleep(3.0) # Wait for peers
            await self.broadcast_game_start()

    async def broadcast_game_start(self):
        from .state import build_deck
        deck = build_deck()
        
        # Each player gets 5 cards + their own remaining deck
        # We broadcast the SHARED central cards and the fact the game started
        center1 = deck.pop()
        center2 = deck.pop()
        
        msg = Message(
            type="GAME_ACTION",
            src=self.config.node_id,
            dst="all",
            id=str(uuid.uuid4()),
            ts=await self.state.get_next_ts(),
            payload={
                "action": "GAME_START",
                "center_piles": [[center1], [center2]],
                "initial_log": "Game Started! Initial center cards dealt."
            }
        )
        await self.network.broadcast(msg)
        await self.handle_game_action(msg) # Apply locally too

    async def broadcast_log(self, category: str, message: str, details: Any = None):
        log_msg = Message(
            type="GAME_ACTION",
            src=self.config.node_id,
            dst="all",
            id=str(uuid.uuid4()),
            ts=await self.state.get_next_ts(),
            payload={
                "action": "LOG_EVENT",
                "category": category,
                "message": message,
                "details": details
            }
        )
        await self.network.broadcast(log_msg)
        self.state.add_log(category, message, details)
        await self.network.notify_ui(self.state.to_ui_dict())

    async def handle_peer_message(self, msg: Message):
        await self.state.update_ts(msg.ts)
        
        if msg.type == "TOKEN":
            await self.token_proto.handle_token(msg)
        elif msg.type == "MUTEX_REQUEST":
            await self.mutex_proto.handle_request(msg)
        elif msg.type == "MUTEX_REPLY":
            await self.mutex_proto.handle_reply(msg)
        elif msg.type == "GAME_ACTION":
            await self.handle_game_action(msg)
        
        await self.network.notify_ui(self.state.to_ui_dict())

    async def handle_game_action(self, msg: Message):
        action = msg.payload.get("action")
        if action == "GAME_START":
            self.state.center_piles = msg.payload["center_piles"]
            self.state.add_log("game", msg.payload["initial_log"])
            
            # Initial local hand/deck generation (private)
            from .state import build_deck
            full_deck = build_deck()
            # deterministic seed if we want same decks, but user said "decks are different"
            # so we just pop our own.
            self.state.hand = [full_deck.pop() for _ in range(5)]
            self.state.deck = full_deck
            
        elif action == "TOKEN_ACQUIRED":
            holder = msg.src
            self.state.token_holder = holder
            self.state.add_log("token", f"Token acquired by {holder}")
            
        elif action == "PLAY_CARD":
            pile_idx = msg.payload["pile_idx"]
            card = msg.payload["card"]
            self.state.center_piles[pile_idx].append(card)
            
            # If it was ME, remove from my actual hand
            if msg.src == self.config.node_id:
                matching = [c for c in self.state.hand if c["rank"] == card["rank"] and c["suit"] == card["suit"]]
                if matching:
                    self.state.hand.remove(matching[0])
            
            self.state.add_log("game", f"{msg.src} played {card_label(card)} → pile {pile_idx + 1}")
            self.state.token_holder = None
            
        elif action == "TOKEN_REVOKED":
            self.state.add_log("token", f"Token revoked from {msg.src} (Timeout)")
            self.state.token_holder = None
            
        elif action == "PLAYER_WON":
            self.state.winner = msg.payload["winner"]
            self.state.add_log("game", f"🏆 {msg.payload['winner']} WON THE GAME!")

        elif action == "LOG_EVENT":
            self.state.add_log(msg.payload["category"], msg.payload["message"])

    async def ui_play_card(self, pile_idx: int, card: dict):
        if self.state.winner or self.state.token_holder:
            return False

        # 1. Must be in hand
        if not self.state.player_has_card(card):
            return False

        # 2. Check if valid on top
        top_card = self.state.center_piles[pile_idx][-1]
        if not is_valid_play(top_card, card):
            return False

        # 3. COMPETITION: Request move token (Mutex)
        # The fastest player (earliest TS) will get it.
        self.state.mutex_event.clear()
        await self.mutex_proto.request_access()
        
        try:
            # Wait for acquisition (the Ring/Protocol handles the 'fastest' logic)
            await asyncio.wait_for(self.state.mutex_event.wait(), timeout=3.0)
        except asyncio.TimeoutError:
            return False

        if self.state.mutex_state != "HELD":
            return False

        # 4. TOKEN ACQUIRED - Broadcast Acquisition
        acq_msg = Message(
            type="GAME_ACTION",
            src=self.config.node_id,
            dst="all",
            id=str(uuid.uuid4()),
            ts=await self.state.get_next_ts(),
            payload={"action": "TOKEN_ACQUIRED"}
        )
        await self.network.broadcast(acq_msg)
        await self.handle_game_action(acq_msg)

        # 5. START 2s TIMEOUT
        self.token_timeout_task = asyncio.create_task(self._token_timeout_handler())

        # 6. COMMIT PLAY
        # Re-check validity after acquisition
        top_card = self.state.center_piles[pile_idx][-1]
        if is_valid_play(top_card, card):
            # Success! Cancel timeout
            if self.token_timeout_task:
                self.token_timeout_task.cancel()

            play_msg = Message(
                type="GAME_ACTION",
                src=self.config.node_id,
                dst="all",
                id=str(uuid.uuid4()),
                ts=await self.state.get_next_ts(),
                payload={"action": "PLAY_CARD", "pile_idx": pile_idx, "card": card}
            )
            await self.network.broadcast(play_msg)
            await self.handle_game_action(play_msg)
            
            # Win check
            if len(self.state.hand) == 0:
                win_msg = Message(
                    type="GAME_ACTION",
                    src=self.config.node_id,
                    dst="all",
                    id=str(uuid.uuid4()),
                    ts=await self.state.get_next_ts(),
                    payload={"action": "PLAYER_WON", "winner": self.config.node_id}
                )
                await self.network.broadcast(win_msg)
                await self.handle_game_action(win_msg)

        # 7. Always release token at end
        await self.mutex_proto.release()
        return True

    async def _token_timeout_handler(self):
        try:
            await asyncio.sleep(2.0)
            # If we are here, player took too long
            rev_msg = Message(
                type="GAME_ACTION",
                src=self.config.node_id,
                dst="all",
                id=str(uuid.uuid4()),
                ts=await self.state.get_next_ts(),
                payload={"action": "TOKEN_REVOKED"}
            )
            await self.network.broadcast(rev_msg)
            await self.handle_game_action(rev_msg)
            await self.mutex_proto.release()
        except asyncio.CancelledError:
            pass

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
        
        # Broadcast that we drew so others can log it
        draw_msg = Message(
            type="GAME_ACTION",
            src=self.config.node_id,
            dst="all",
            id=str(uuid.uuid4()),
            ts=await self.state.get_next_ts(),
            payload={"action": "PLAYER_DREW"}
        )
        await self.network.broadcast(draw_msg)
        
        return True

    async def ui_shuffle_deck(self):
        """Reset center piles (requires TOKEN)."""
        if await self.token_proto.use_token_for_action("Reset Center Piles"):
            from .state import build_deck
            tmp = build_deck()
            new_piles = [[tmp.pop()], [tmp.pop()]]
            self.state.center_piles = new_piles
            self.state.winner = None
            self.state.add_log("game", "Center piles reset via Token")
            
            msg = Message(
                type="GAME_ACTION",
                src=self.config.node_id,
                dst="all",
                id=str(uuid.uuid4()),
                ts=await self.state.get_next_ts(),
                payload={
                    "action": "RESET_PILES",
                    "center_piles": new_piles
                }
            )
            await self.network.broadcast(msg)
            return True
        return False
