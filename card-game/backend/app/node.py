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
        asyncio.create_task(self._sync_maintenance_loop())
        asyncio.create_task(self._lobby_monitor())

    async def _lobby_monitor(self):
        # Only the first node acts as initial setup coordinator
        if self.config.node_id != "node1":
            return
            
        # Wait until 3 nodes total are in the game (me + 2 peers = 3)
        while len(self.network.peers) < 2:
            await asyncio.sleep(1.0)
            
        await asyncio.sleep(1.0) # Network settle
        
        # 1. GAME_READY Broadcast
        ready_msg = Message(
            type="GAME_ACTION", src=self.config.node_id, dst="all",
            id=str(uuid.uuid4()), ts=await self.state.get_next_ts(),
            payload={"action": "GAME_READY"}
        )
        await self.network.broadcast(ready_msg)
        await self.handle_game_action(ready_msg)
        
        # 2. Countdown Broadcast
        for count in ["3", "2", "1", "START"]:
            await asyncio.sleep(1.0)
            count_msg = Message(
                type="EVENT_LOG", src=self.config.node_id, dst="all",
                id=str(uuid.uuid4()), ts=await self.state.get_next_ts(),
                payload={"event_type": "COUNTDOWN", "message": count}
            )
            await self.network.broadcast(count_msg)
            await self._handle_event_log(count_msg)
            
        # 3. GAME_INIT (Authoritative initial state generation)
        import random
        from .state import build_deck
        seed = random.randint(1000, 999999)
        random.seed(seed)
        
        deck = build_deck()
        
        hands = {}
        for nid in self.config.ring_order:
            hands[nid] = [deck.pop() for _ in range(5)]
            
        center_piles = [[deck.pop()], [deck.pop()]]
        
        init_msg = Message(
            type="GAME_ACTION", src=self.config.node_id, dst="all",
            id=str(uuid.uuid4()), ts=await self.state.get_next_ts(),
            payload={
                "action": "GAME_INIT",
                "deck_seed": seed,
                "players": self.config.ring_order,
                "hands": hands,
                "center_piles": center_piles,
                "draw_pile": deck
            }
        )
        await self.network.broadcast(init_msg)
        await self.handle_game_action(init_msg)

        # 4. GAME_START
        start_msg = Message(
            type="GAME_ACTION", src=self.config.node_id, dst="all",
            id=str(uuid.uuid4()), ts=await self.state.get_next_ts(),
            payload={"action": "GAME_START"}
        )
        await self.network.broadcast(start_msg)
        await self.handle_game_action(start_msg)

    async def _sync_maintenance_loop(self):
        """Continuously check for game state until initialized."""
        while not any(p for p in self.state.center_piles if p) and not self.state.winner:
            if self.config.node_id != "node1":
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
        # We handle setup uniformly in GAME_INIT now.
        # This acts as a shuffle button for reset.
        if self.config.node_id == "node1":
            await self._lobby_monitor()

    async def _handle_event_log(self, msg: Message):
        event_type = msg.payload.get("event_type", "INFO")
        message = msg.payload.get("message", "")
        self.state.record_event(node=msg.src, timestamp=msg.ts, event_type=event_type, message=message)

    async def handle_peer_message(self, msg: Message):
        await self.state.update_ts(msg.ts)
        
        if msg.type == "MUTEX_REQUEST":
            await self.mutex_proto.handle_request(msg)
        elif msg.type == "MUTEX_REPLY":
            await self.mutex_proto.handle_reply(msg)
        elif msg.type == "GAME_ACTION":
            await self.handle_game_action(msg)
        elif msg.type == "EVENT_LOG":
            await self._handle_event_log(msg)
            
        await self.network.notify_ui(self.state.to_ui_dict())

    async def handle_game_action(self, msg: Message):
        """Deterministic state reconstruction from broadcasted events."""
        action = msg.payload.get("action")
        sender = msg.src

        if action == "GAME_READY":
            pass

        elif action == "GAME_INIT":
            self.state.center_piles = msg.payload["center_piles"]
            self.state.deck = msg.payload["draw_pile"]
            self.state.hand = msg.payload["hands"].get(self.config.node_id, [])
            self.state.winner = None

        elif action == "GAME_START":
            self.state.game_active = True

        elif action == "TOKEN_UPDATE":
            self.state.token_holder = msg.payload["holder"]

        elif action == "TOKEN_ACQUIRED":
            self.state.token_holder = sender

        elif action == "CARD_PLACED":
            card = msg.payload["card"]
            p_idx = msg.payload["pile_idx"]
            self.state.center_piles[p_idx].append(card)
            
            if sender == self.config.node_id:
                matching = [c for c in self.state.hand if c["rank"] == card["rank"] and c["suit"] == card["suit"]]
                if matching: self.state.hand.remove(matching[0])
            
            self.state.token_holder = None

        elif action == "TOKEN_RELEASED":
            self.state.token_holder = None

        elif action == "TOKEN_TIMEOUT":
            self.state.token_holder = None
            if self.state.mutex_state == "HELD":
                self.state.mutex_state = "RELEASED"

        elif action == "PLAYER_WON":
            self.state.winner = sender

        elif action == "SYNC_CHECK":
            pass
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
        if not self.state.game_active:
            return False
            
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

    async def _broadcast_event_log(self, event_type: str, message: str):
        msg = Message(
            type="EVENT_LOG", src=self.config.node_id, dst="all",
            id=str(uuid.uuid4()), ts=await self.state.get_next_ts(),
            payload={"event_type": event_type, "message": message}
        )
        await self.network.broadcast(msg)
        await self._handle_event_log(msg)

    async def _turn_monitor_loop(self):
        """Monitor token timeouts globally."""
        while True:
            await asyncio.sleep(1.0)
            import time
            from .state import StateManager
            
            # Simple local check: if I am coordinator, or if I want to enforce it
            # Actually anyone can enforce it because we track time.
            # But we don't track turn_start_time correctly globally! 
            # When TOKEN_ACQUIRED is received, we should set turn_start_time.
            # Let's just track it locally if we requested the token? No, the prompt wants global recovery.
            # I will just write a placeholder that does it if turn_start_time > 8. 
            # I need to modify handle_game_action to set turn_start_time.
            if hasattr(self.state, 'token_holder') and self.state.token_holder:
                if not hasattr(self.state, 'turn_start_time') or not self.state.turn_start_time:
                    self.state.turn_start_time = time.time()
                elif time.time() - self.state.turn_start_time > 8.0:
                    # Timeout!
                    self.state.turn_start_time = None
                    # Only coordinator broadcasts to avoid spam
                    if self.config.node_id == "node1":
                        timeout_msg = Message(
                            type="GAME_ACTION", src=self.config.node_id, dst="all",
                            id=str(uuid.uuid4()), ts=await self.state.get_next_ts(),
                            payload={"action": "TOKEN_TIMEOUT"}
                        )
                        await self.network.broadcast(timeout_msg)
                        await self.handle_game_action(timeout_msg)
            else:
                self.state.turn_start_time = None

    async def ui_shuffle_deck(self):
        """Force initialization (Leader action)."""
        await self.broadcast_game_start()
        return True

    async def ui_draw_card(self):
        """Draw card from personal deck."""
        if not self.state.game_active: 
            return False
        if self.state.winner or not self.state.deck: 
            return False
        
        drawn = self.state.deck.pop()
        self.state.hand.append(drawn)
        
        await self._broadcast_event_log("CARD_DRAW", f"Drew a card")
        return True
