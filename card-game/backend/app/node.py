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
        
        # Start turn timeout monitor
        asyncio.create_task(self._turn_monitor_loop())

        # Start periodic global snapshot (initiator: node1 only)
        if self.config.node_id == "node1":
            asyncio.create_task(self._periodic_snapshot_loop())

    async def _periodic_snapshot_loop(self):
        """Triggers a Chandy-Lamport snapshot every 15 seconds."""
        await asyncio.sleep(5) # Give some time to connect
        while True:
            try:
                await self.snapshot_proto.initiate()
            except Exception as e:
                self.state.add_log("system", f"Periodic snapshot failed: {e}")
            await asyncio.sleep(15)

    async def ui_distribute_cards(self):
        """Node 1 manually broadcasts initial game state when triggered by UI."""
        if self.config.node_id != "node1":
            return
            
        from .state import build_deck
        full_deck = build_deck()
        
        # Determine order of players (from ring_order)
        ring = self.config.ring_order
        hands = {}
        for i, nid in enumerate(ring):
            hands[nid] = [full_deck.pop() for _ in range(5)]
        
        # Remaining deck and center piles
        cp1 = [full_deck.pop()]
        cp2 = [full_deck.pop()]
        
        sync_payload = {
            "action": "INITIAL_SYNC",
            "hands": hands,
            "center_piles": [cp1, cp2],
            "deck": full_deck
        }
        
        # Check active connections
        active_ids = list(self.network.peers.keys())
        all_peers = list(self.config.peers.keys())
        missing = [p for p in all_peers if p not in active_ids]
        if missing:
            self.state.add_log("system", f"WARNING: Distributing cards but peers are missing: {', '.join(missing)}")
        
        
        msg = Message(
            type="GAME_ACTION",
            src=self.config.node_id,
            dst="all",
            id=str(uuid.uuid4()),
            ts=await self.state.get_next_ts(),
            payload=sync_payload
        )
        await self.network.broadcast(msg)
        # Apply locally too
        await self.handle_game_action(msg)

    async def _turn_monitor_loop(self):
        """Check for turn timeouts every second."""
        while True:
            await asyncio.sleep(1)
            import time
            if self.state.has_token and self.state.turn_start_time:
                elapsed = time.time() - self.state.turn_start_time
                if elapsed > 5: # 5 second timeout based on feedback
                    self.state.add_log("game", "Turn timeout — releasing automatically")
                    await self.ui_release_turn()

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
        if action == "INITIAL_SYNC":
            self.state.center_piles = msg.payload["center_piles"]
            self.state.deck = msg.payload["deck"]
            my_hand = msg.payload["hands"].get(self.config.node_id, [])
            self.state.hand = my_hand
            self.state.add_log("game", f"Game state synced by {msg.src}")
        elif action == "TURN_UPDATE":
            self.state.current_turn_holder = msg.payload["holder"]
            self.state.add_log("game", f"Turn is now held by: {msg.payload['holder']}")
        elif action == "PLAY_CARD":
            pile_idx = msg.payload["pile_idx"]
            card = msg.payload["card"]
            self.state.center_piles[pile_idx].append(card)
            self.state.add_log("game", f"Player {msg.src} played {card_label(card)} to pile {pile_idx + 1}")
        elif action == "RESET_PILES":
            self.state.center_piles = msg.payload["center_piles"]
            self.state.winner = None
            self.state.add_log("game", f"Center piles reset by {msg.src}")
        elif action == "PLAYER_WON":
            winner_id = msg.payload["winner"]
            self.state.winner = winner_id
            self.state.add_log("game", f"🏆 {winner_id} has WON the game by emptying their hand!")

    async def ui_acquire_turn(self):
        """Grabbing the turn via Mutex."""
        if self.state.has_token:
            return True
            
        self.state.mutex_event.clear()
        await self.mutex_proto.request_access()
        try:
            # Wait for replies from everyone
            await asyncio.wait_for(self.state.mutex_event.wait(), timeout=5.0)
        except asyncio.TimeoutError:
            self.state.add_log("mutex", "Failed to acquire turn (timeout)")
            if self.state.mutex_state == "WANTED":
                self.state.mutex_state = "RELEASED"
            return False

        if self.state.mutex_state == "HELD":
            self.state.has_token = True
            import time
            self.state.turn_start_time = time.time()
            self.state.current_turn_holder = self.config.node_id
            
            # Broadcast turn update
            msg = Message(
                type="GAME_ACTION",
                src=self.config.node_id,
                dst="all",
                id=str(uuid.uuid4()),
                ts=await self.state.get_next_ts(),
                payload={"action": "TURN_UPDATE", "holder": self.config.node_id}
            )
            await self.network.broadcast(msg)
            return True
        return False

    async def ui_release_turn(self):
        """Release the turn (mutex)."""
        if not self.state.has_token:
            return
            
        self.state.has_token = False
        self.state.turn_start_time = None
        self.state.current_turn_holder = None
        await self.mutex_proto.release()
        
        # Broadcast turn update (none holding)
        msg = Message(
            type="GAME_ACTION",
            src=self.config.node_id,
            dst="all",
            id=str(uuid.uuid4()),
            ts=await self.state.get_next_ts(),
            payload={"action": "TURN_UPDATE", "holder": None}
        )
        await self.network.broadcast(msg)

    async def ui_play_card(self, pile_idx: int, card: dict):
        if self.state.winner:
            return False
        if not self.state.has_token:
            self.state.add_log("game", "You must acquire the turn first!")
            return False

        # Must be in hand
        matching = [c for c in self.state.hand if c["rank"] == card["rank"] and c["suit"] == card["suit"]]
        if not matching:
            return False

        # Validity check
        top_card = self.state.center_piles[pile_idx][-1]
        if not is_valid_play(top_card, card):
            self.state.add_log("game", f"Invalid play: {card_label(card)} on {card_label(top_card)}")
            return False

        # Commit
        self.state.hand.remove(matching[0])
        self.state.center_piles[pile_idx].append(card)
        
        # Reset timeout on activity
        import time
        self.state.turn_start_time = time.time()

        # Broadcast
        play_msg = Message(
            type="GAME_ACTION",
            src=self.config.node_id,
            dst="all",
            id=str(uuid.uuid4()),
            ts=await self.state.get_next_ts(),
            payload={"action": "PLAY_CARD", "pile_idx": pile_idx, "card": card}
        )
        await self.network.broadcast(play_msg)

        # Win check
        if len(self.state.hand) == 0:
            self.state.winner = self.config.node_id
            win_msg = Message(
                type="GAME_ACTION",
                src=self.config.node_id,
                dst="all",
                id=str(uuid.uuid4()),
                ts=await self.state.get_next_ts(),
                payload={"action": "PLAYER_WON", "winner": self.config.node_id}
            )
            await self.network.broadcast(win_msg)

        # Auto-release turn after placing a card based on feedback
        await self.ui_release_turn()
        return True

    async def ui_draw_card(self):
        if self.state.winner or not self.state.deck:
            return False
            
        # Draw and add to hand
        drawn = self.state.deck.pop() # Everyone has same deck order, but pop is local?
        # WAIT: if everyone has same deck, and I draw, I need to tell others which card I took?
        # NO: the user said "deck is same for everyone". In a real P2P game, we'd need to sync deck state.
        # But for this simple version, each player having the "same" starting draw pile is what was requested.
        
        # Reset timeout on activity
        if self.state.has_token:
            import time
            self.state.turn_start_time = time.time()

        self.state.hand.append(drawn)
        self.state.add_log("game", f"Drew {card_label(drawn)}")
        return True

    async def ui_shuffle_deck(self):
        """Reset center piles (requires TOKEN/TURN)."""
        if not self.state.has_token:
            self.state.add_log("game", "Need turn to reset piles")
            return False
            
        from .state import build_deck
        tmp = build_deck()
        piles = [[tmp.pop()], [tmp.pop()]]
        
        msg = Message(
            type="GAME_ACTION",
            src=self.config.node_id,
            dst="all",
            id=str(uuid.uuid4()),
            ts=await self.state.get_next_ts(),
            payload={"action": "RESET_PILES", "center_piles": piles}
        )
        await self.network.broadcast(msg)
        await self.handle_game_action(msg)
        return True
