import asyncio
import json
import websockets
from typing import Dict, Callable, Awaitable, List, Optional, Any
from .models import Message, NodeConfig
from .utils import log_debug

class NetworkManager:
    def __init__(self, config: NodeConfig, on_message: Callable[[Message], Awaitable[None]]):
        self.config = config
        self.on_message = on_message
        self.peers: Dict[str, websockets.WebSocketClientProtocol] = {}
        self.ui_websockets = set()
        self.latency_min = 0.05 # 50ms
        self.latency_max = 0.2  # 200ms

    async def connect_to_peers(self):
        for node_id, url in self.config.peers.items():
            asyncio.create_task(self._maintain_connection(node_id, url))

    async def _maintain_connection(self, node_id: str, url: str):
        while True:
            try:
                print(f"[{self.config.node_id}] Attempting to connect to peer {node_id} at {url}...")
                async with websockets.connect(url, open_timeout=5, close_timeout=5) as ws:
                    print(f"[{self.config.node_id}] SUCCESS: Connected to peer {node_id}")
                    self.peers[node_id] = ws
                    # Send hello to identify ourselves?? 
                    # In this setup, we assume the server knows who is connecting or we include 'src' in every message.
                    async for message_info in ws:
                        data = json.loads(message_info)
                        msg = Message(**data)
                        await self.on_message(msg)
            except Exception as e:
                print(f"Connection lost to {node_id} ({url}): {e}")
                if node_id in self.peers:
                    del self.peers[node_id]
            await asyncio.sleep(2) # Retry delay

    async def send_to_peer(self, node_id: str, msg: Message):
        if node_id in self.peers:
            # Simulate network latency
            import random
            delay = random.uniform(self.latency_min, self.latency_max)
            await asyncio.sleep(delay)
            
            try:
                await self.peers[node_id].send(msg.model_dump_json())
            except Exception as e:
                print(f"Failed to send to {node_id}: {e}")

    async def broadcast(self, msg: Message, exclude: Optional[List[str]] = None):
        exclude = exclude or []
        tasks = []
        for peer_id in self.config.peers.keys():
            if peer_id not in exclude:
                tasks.append(self.send_to_peer(peer_id, msg))
        if tasks:
            await asyncio.gather(*tasks)

    async def notify_ui(self, state_dict: Dict[str, Any]):
        if not self.ui_websockets:
            return
        
        payload = json.dumps({"type": "STATE_UPDATE", "data": state_dict})
        disconnected = set()
        for ws in self.ui_websockets:
            try:
                await ws.send_text(payload)
            except Exception:
                disconnected.add(ws)
        
        for ws in disconnected:
            self.ui_websockets.remove(ws)
