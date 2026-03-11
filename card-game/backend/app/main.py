import asyncio
import json
import argparse
import uvicorn
import sys
import os
import logging
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional, Set, Dict

from .models import NodeConfig, Message
from .node import Node

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("SignalingServer")

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global node instance
node: Optional[Node] = None

class SignalingServer:
    def __init__(self, max_peers: int = 3):
        self.peers: Dict[str, Dict] = {} # node_id -> {"ws": websocket, "address": "ip:port"}
        self.max_peers = max_peers

    async def register(self, node_id: str, address: str, websocket: WebSocket):
        if len(self.peers) >= self.max_peers and node_id not in self.peers:
            logger.warning(f"Registration rejected for {node_id}: Full")
            await websocket.send_text(json.dumps({"type": "ERROR", "message": "Server full"}))
            return False
            
        self.peers[node_id] = {"ws": websocket, "address": address}
        logger.info(f"Registered {node_id} at {address}. Active peers: {list(self.peers.keys())}")
        
        # Broadcast the full peer map to everyone immediately
        peer_list = {nid: p["address"] for nid, p in self.peers.items()}
        await self.broadcast({"type": "PEER_DISCOVERY", "peers": peer_list})
        return True

    def deregister(self, node_id: str):
        if node_id in self.peers:
            del self.peers[node_id]
            logger.info(f"Deregistered {node_id}. Remaining: {list(self.peers.keys())}")
            # Notify others
            asyncio.create_task(self.broadcast({
                "type": "PEER_DISCOVERY", 
                "peers": {nid: p["address"] for nid, p in self.peers.items()}
            }))

    async def broadcast(self, message: dict):
        disconnected = []
        for nid, p in self.peers.items():
            try:
                await p["ws"].send_text(json.dumps(message))
            except Exception:
                disconnected.append(nid)
        
        for nid in disconnected:
            self.deregister(nid)

signaling = SignalingServer(max_peers=3)

@app.on_event("startup")
async def startup_event():
    global node
    if node:
        asyncio.create_task(node.start())

@app.websocket("/ws/signaling")
async def signaling_endpoint(websocket: WebSocket):
    await websocket.accept()
    node_id = None
    try:
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)
            
            if msg.get("type") == "REGISTER":
                node_id = msg.get("node_id")
                address = msg.get("address")
                if not await signaling.register(node_id, address, websocket):
                    break
            
            elif msg.get("type") == "SIGNAL":
                # Forward signaling messages (for synchronization/etc if needed)
                target = msg.get("dst")
                if target in signaling.peers:
                    await signaling.peers[target]["ws"].send_text(data)
    except Exception:
        pass
    finally:
        if node_id:
            signaling.deregister(node_id)

@app.websocket("/ws/ui")
async def ui_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        # Send initial local view
        if node:
            await websocket.send_text(json.dumps({
                "type": "STATE_UPDATE", 
                "data": node.state.to_ui_dict()
            }))
        
        # Listen for UI commands
        while True:
            data = await websocket.receive_text()
            cmd = json.loads(data)
            if node:
                action = cmd.get("action")
                if action == "play_card":
                    await node.ui_play_card(cmd["pile_idx"], cmd["card"])
                elif action == "draw_card":
                    await node.ui_draw_card()
                elif action == "shuffle":
                    await node.ui_shuffle_deck()
    except Exception:
        pass

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="nodes/node1.json")
    parser.add_argument("--signaling-url", help="URL of the signaling server (e.g. ws://node1_ip:8001/ws/signaling)")
    args = parser.parse_args()

    with open(args.config, "r") as f:
        config_data = json.load(f)
        from .models import NodeConfig
        config = NodeConfig(**config_data)

    global node
    node = Node(config)
    
    # If a signaling URL is provided, node will act as a client
    if args.signaling_url:
        node.signaling_url = args.signaling_url

    logger.info(f"Node {config.node_id} starting UI on port {config.ui_port}")
    uvicorn.run(app, host="0.0.0.0", port=config.ui_port)

if __name__ == "__main__":
    main()
