import asyncio
import uuid
import json
import logging
import websockets
from typing import Dict, Any, List, Optional

from .models import Message, NodeConfig
from .state import StateManager
from .network import NetworkManager
from .protocols.mutex import MutexProtocol
from .protocols.snapshot import SnapshotProtocol
from .utils import log_debug, is_valid_play, card_label

logger = logging.getLogger("Node")

class Node:
    def __init__(self, config: NodeConfig):
        self.config = config
        self.state = StateManager(config.node_id)
        self.network = NetworkManager(config, self.handle_peer_message)
        
        # Protocols
        self.mutex_proto = MutexProtocol(config.node_id, self.state, self.network)
        self.snapshot_proto = SnapshotProtocol(config.node_id, self.state, self.network)
        
        self.signaling_url: Optional[str] = None
        self.signaling_task: Optional[asyncio.Task] = None

    async def start(self):
        # Start TCP P2P Listener
        await self.network.start_server()
        
        # Start Signaling Client if URL provided
        if self.signaling_url:
            self.signaling_task = asyncio.create_task(self._run_signaling_client())
        else:
            # If no signaling URL, assume I am the signaling host
            # I still need to 'register' myself conceptually for local mesh discovery
            # But main.py handles the discovery broadcast.
            # For simplicity, Node 1 (host) will just register itself once its server is up.
            local_url = f"ws://localhost:{self.config.ui_port}/ws/signaling"
            self.signaling_url = local_url
            self.signaling_task = asyncio.create_task(self._run_signaling_client())

    async def _run_signaling_client(self):
        """Connects to the signaling server and handles discovery."""
        while True:
            try:
                logger.info(f"Connecting to signaling server at {self.signaling_url}")
                async with websockets.connect(self.signaling_url) as ws:
                    # Register this node
                    addr = f"{self.config.listen_host}:{self.config.listen_port}"
                    # If listen_host is 0.0.0.0, we should probably send our actual reachable IP.
                    # For now, let's assume the network can reach the IP defined in the registry.
                    # A better way is to rely on signaling to pass reachable addresses.
                    await ws.send(json.dumps({
                        "type": "REGISTER",
                        "node_id": self.config.node_id,
                        "address": addr
                    }))
                    
                    while True:
                        msg_str = await ws.recv()
                        msg = json.loads(msg_str)
                        
                        if msg["type"] == "PEER_DISCOVERY":
                            peers = msg["peers"]
                            logger.info(f"Discovery update: {list(peers.keys())}")
                            await self.network.handle_discovery(peers)
            except Exception as e:
                logger.error(f"Signaling client error: {e}. Retrying...")
                await asyncio.sleep(5)

    async def handle_peer_message(self, msg: Message):
        """Entry point for all P2P mesh messages."""
        await self.state.update_ts(msg.ts)
        
        if msg.type == "MUTEX_REQUEST":
            await self.mutex_proto.handle_request(msg)
        elif msg.type == "MUTEX_REPLY":
            await self.mutex_proto.handle_reply(msg)
        elif msg.type == "GAME_ACTION":
            await self.handle_game_action(msg)
            
        # Update local UI if needed (main.py handles UI broadcats, 
        # so node should notify its local signaling ws if it were acting as sync hub,
        # but here each Node has its own main.py UI loop.)
        # We can trigger a notify call if Node had a backref to the UI manager.

    async def _initialize_game(self):
        """Distributed game start (Node 1 only)."""
        if len(self.network.peers) < 2:
            logger.warning("Not enough peers to start game (need 3 total)")
            return

        import random
        from .state import build_deck
        deck = build_deck()
        
        # Symmetrically assign hands
        all_players = sorted([self.config.node_id] + list(self.network.peers.keys()))
        hands = {}
        for nid in all_players:
            hands[nid] = [deck.pop() for _ in range(5)]
            
        center_piles = [[deck.pop()], [deck.pop()]]
        
        init_msg = Message(
            type="GAME_ACTION", src=self.config.node_id, dst="all",
            id=str(uuid.uuid4()), ts=await self.state.get_next_ts(),
            payload={
                "action": "GAME_INIT",
                "hands": hands,
                "center_piles": center_piles,
                "draw_pile": deck
            }
        )
        await self.network.broadcast(init_msg)
        await self.handle_game_action(init_msg)

    async def handle_game_action(self, msg: Message):
        action = msg.payload.get("action")
        sender = msg.src

        if action == "GAME_INIT":
            self.state.center_piles = msg.payload["center_piles"]
            self.state.deck = msg.payload["draw_pile"]
            self.state.hand = msg.payload["hands"].get(self.config.node_id, [])
            self.state.game_active = True
            self.state.winner = None

        elif action == "CARD_PLACED":
            card = msg.payload["card"]
            p_idx = msg.payload["pile_idx"]
            self.state.center_piles[p_idx].append(card)
            
            if sender == self.config.node_id:
                matching = [c for c in self.state.hand if c["rank"] == card["rank"] and c["suit"] == card["suit"]]
                if matching: self.state.hand.remove(matching[0])

        elif action == "PLAYER_WON":
            self.state.winner = sender
            self.state.game_active = False

    async def ui_play_card(self, pile_idx: int, card: dict):
        if not self.state.game_active or self.state.winner:
            return False

        # Mutex Check (Competition)
        self.state.mutex_event.clear()
        await self.mutex_proto.request_access()
        try:
            await asyncio.wait_for(self.state.mutex_event.wait(), timeout=3.0)
        except asyncio.TimeoutError:
            return False

        if self.state.mutex_state != "HELD":
            return False

        # Valid Move?
        top = self.state.center_piles[pile_idx][-1]
        if not is_valid_play(top, card):
            await self.mutex_proto.release()
            return False

        # Broadcast
        play_msg = Message(
            type="GAME_ACTION", src=self.config.node_id, dst="all",
            id=str(uuid.uuid4()), ts=await self.state.get_next_ts(),
            payload={"action": "CARD_PLACED", "card": card, "pile_idx": pile_idx}
        )
        await self.network.broadcast(play_msg)
        await self.handle_game_action(play_msg)

        if len(self.state.hand) == 0:
            win_msg = Message(
                type="GAME_ACTION", src=self.config.node_id, dst="all",
                id=str(uuid.uuid4()), ts=await self.state.get_next_ts(),
                payload={"action": "PLAYER_WON"}
            )
            await self.network.broadcast(win_msg)
            await self.handle_game_action(win_msg)

        await self.mutex_proto.release()
        return True

    async def ui_draw_card(self):
        if not self.state.game_active or not self.state.deck:
            return False
        
        # Local draw (simplified for this version)
        drawn = self.state.deck.pop()
        self.state.hand.append(drawn)
        return True

    async def ui_shuffle_deck(self):
        await self._initialize_game()
        return True
