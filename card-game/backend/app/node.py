import asyncio
import uuid
from typing import Dict, Any, List, Optional

from .models import Message, NodeConfig
from .state import StateManager
from .network import NetworkManager
from .protocols.mutex import MutexProtocol
from .protocols.snapshot import SnapshotProtocol
from .utils import log_debug, is_valid_play, card_label

class Node:
    def __init__(self, config: NodeConfig):
        self.config = config
        self.state = StateManager(config.node_id)
        self.network = NetworkManager(config, self.handle_peer_message)
        
        # RICART-AGRAWALA MUTEX: Used to implement "fastest player wins" Token competition
        self.mutex_proto = MutexProtocol(config.node_id, self.state, self.network)
        self.snapshot_proto = SnapshotProtocol(config.node_id, self.state, self.network)
        
        self.token_timeout_task: Optional[asyncio.Task] = None

    async def start(self):
        await self.network.connect_to_peers()
        # Synchronization maintenance task
        asyncio.create_task(self._sync_maintenance_loop())

        # AUTOMATIC START: If I am the leader, try to start after a few seconds
        if self.config.is_initial_token_holder:
            async def auto_start():
                await asyncio.sleep(5.0) # Wait for network to settle
                # Only start if board is still empty
                if not any(p for p in self.state.center_piles if p):
                    await self.broadcast_game_start()
            asyncio.create_task(auto_start())

    async def _sync_maintenance_loop(self):
        """Continuously check for game state until initialized."""
        while not any(p for p in self.state.center_piles if p) and not self.state.winner:
            if not self.config.is_initial_token_holder:
                await self.request_global_sync()
            await asyncio.sleep(5.0)

    async def request_global_sync(self):
        sync_msg = Message(
            type="GAME_ACTION",
            src=self.config.node_id,
            dst="all",
            id=str(uuid.uuid4()),
            ts=await self.state.get_next_ts(),
            payload={"action": "SYNC_CHECK"}
        )
        await self.network.broadcast(sync_msg)

    async def broadcast_game_start(self):
        """Leader (initial token holder) initializes the exact same state for everyone."""
        from .state import build_deck
        deck = build_deck()
        
        # Shared central piles
        c1 = deck.pop()
        c2 = deck.pop()
        
        msg = Message(
            type="GAME_ACTION",
            src=self.config.node_id,
            dst="all",
            id=str(uuid.uuid4()),
            ts=await self.state.get_next_ts(),
            payload={
                "action": "GAME_START",
                "center_piles": [[c1], [c2]],
                "initial_log": f"GAME_START | CENTER_CARDS: [{card_label(c1)}, {card_label(c2)}]"
            }
        )
        await self.network.broadcast(msg)
        await self.handle_game_action(msg)

    async def handle_peer_message(self, msg: Message):
        await self.state.update_ts(msg.ts)
        
        if msg.type == "MUTEX_REQUEST":
            await self.mutex_proto.handle_request(msg)
        elif msg.type == "MUTEX_REPLY":
            await self.mutex_proto.handle_reply(msg)
        elif msg.type == "GAME_ACTION":
            await self.handle_game_action(msg)
        
        await self.network.notify_ui(self.state.to_ui_dict())

    async def handle_game_action(self, msg: Message):
        """Deterministic state reconstruction from broadcasted events."""
        action = msg.payload.get("action")
        sender = msg.src

        if action == "GAME_START":
            self.state.center_piles = msg.payload["center_piles"]
            self.state.add_log("game", msg.payload["initial_log"])
            
            # Setup personal hand/deck from identical seed (or local pop)
            from .state import build_deck
            full_deck = build_deck()
            # Shared central cards identified
            flat_center = [c for p in self.state.center_piles for c in p]
            # Ensure my local deck removes the center cards
            self.state.deck = [c for c in full_deck if c not in flat_center]
            self.state.hand = [self.state.deck.pop() for _ in range(5)]
            self.state.winner = None

        elif action == "TOKEN_ACQUIRED":
            self.state.token_holder = sender
            self.state.add_log("token", f"TOKEN_ACQUIRED | Node: {sender}")

        elif action == "CARD_PLACED":
            card = msg.payload["card"]
            p_idx = msg.payload["pile_idx"]
            self.state.center_piles[p_idx].append(card)
            
            if sender == self.config.node_id:
                matching = [c for c in self.state.hand if c["rank"] == card["rank"] and c["suit"] == card["suit"]]
                if matching: self.state.hand.remove(matching[0])
            
            self.state.add_log("game", f"CARD_PLACED | {sender} played {card_label(card)} → Pile {p_idx+1}")
            self.state.token_holder = None

        elif action == "TOKEN_RELEASED":
            self.state.token_holder = None
            self.state.add_log("token", f"TOKEN_RELEASED | Released by {sender}")

        elif action == "TOKEN_TIMEOUT":
            self.state.token_holder = None
            self.state.add_log("token", f"TOKEN_TIMEOUT | Node {sender} failed to move within 2s")

        elif action == "PLAYER_WON":
            self.state.winner = sender
            self.state.add_log("game", f"🏆 GAME OVER | Winner: {sender}")

        elif action == "PLAYER_DREW":
            if sender != self.config.node_id:
                self.state.add_log("game", f"Node {sender} drew a card")

        elif action == "SYNC_CHECK":
            if any(p for p in self.state.center_piles if p):
                sync_resp = Message(
                    type="GAME_ACTION",
                    src=self.config.node_id,
                    dst=sender,
                    id=str(uuid.uuid4()),
                    ts=await self.state.get_next_ts(),
                    payload={
                        "action": "GAME_START",
                        "center_piles": self.state.center_piles,
                        "initial_log": f"SYNC | Catching up Node {sender}"
                    }
                )
                await self.network.send_to_peer(sender, sync_resp)

    async def ui_play_card(self, pile_idx: int, card: dict):
        """High-speed move attempt with competition and timeout."""
        if self.state.winner or self.state.token_holder:
            return False

        # Preliminary check
        top = self.state.center_piles[pile_idx][-1] if self.state.center_piles[pile_idx] else None
        if not top or not is_valid_play(top, card):
            return False

        # 1. COMPETITION: Request move token (Mutex)
        self.state.mutex_event.clear()
        await self.mutex_proto.request_access()
        
        try:
            # First-come-first-served based on timestamp
            await asyncio.wait_for(self.state.mutex_event.wait(), timeout=3.0)
        except asyncio.TimeoutError:
            return False

        if self.state.mutex_state != "HELD":
            return False

        # 2. TOKEN HOLDER - Broadcast acquisition immediately
        acq_msg = await self._broadcast_action("TOKEN_ACQUIRED")
        await self.handle_game_action(acq_msg)

        # 3. Handle move / Timeout
        try:
            # We wrap the commitment in a 2s timeout envelope
            await asyncio.wait_for(self._commit_move(pile_idx, card), timeout=2.0)
            await self._broadcast_action("TOKEN_RELEASED")
        except asyncio.TimeoutError:
            # Node took too long to complete the network broadcast of the card!
            timeout_msg = await self._broadcast_action("TOKEN_TIMEOUT")
            await self.handle_game_action(timeout_msg)
        finally:
            await self.mutex_proto.release()
            self.state.token_holder = None
        
        return True

    async def _commit_move(self, pile_idx: int, card: dict):
        """Actual commitment of the card while holding the token."""
        # Confirm validity again
        top = self.state.center_piles[pile_idx][-1]
        if is_valid_play(top, card):
            play_msg = await self._broadcast_action("CARD_PLACED", {"card": card, "pile_idx": pile_idx})
            await self.handle_game_action(play_msg)
            
            if len(self.state.hand) == 0:
                win_msg = await self._broadcast_action("PLAYER_WON")
                await self.handle_game_action(win_msg)
        else:
            # Validity changed between request and acquisition
            pass

    async def _broadcast_action(self, action_name: str, payload_data: Optional[dict] = None) -> Message:
        p = {"action": action_name}
        if payload_data: p.update(payload_data)
        msg = Message(
            type="GAME_ACTION", src=self.config.node_id, dst="all",
            id=str(uuid.uuid4()), ts=await self.state.get_next_ts(),
            payload=p
        )
        await self.network.broadcast(msg)
        return msg

    async def ui_shuffle_deck(self):
        """Force initialization (Leader action)."""
        await self.broadcast_game_start()
        return True

    async def ui_draw_card(self):
        """Draw card from personal deck."""
        if self.state.winner or not self.state.deck: return False
        drawn = self.state.deck.pop()
        self.state.hand.append(drawn)
        await self._broadcast_action("PLAYER_DREW")
        return True
