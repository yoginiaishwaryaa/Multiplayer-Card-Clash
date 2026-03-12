import asyncio
import json
import argparse
import uvicorn
import sys
import os
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional

from .models import NodeConfig, Message
from .node import Node

from contextlib import asynccontextmanager

# Global node instance
node: Optional[Node] = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    if node:
        asyncio.create_task(node.start())
    yield

app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
async def health():
    if not node:
        return {"status": "starting"}
    return {"status": "ok", "node_id": node.config.node_id}

@app.get("/config")
async def get_config():
    if not node:
        return {}
    return node.config

@app.websocket("/ws/ui")
async def websocket_ui(websocket: WebSocket):
    await websocket.accept()
    if not node:
        await websocket.close()
        return
    
    node.network.ui_websockets.add(websocket)
    try:
        # Send initial state
        await websocket.send_text(json.dumps({
            "type": "STATE_UPDATE", 
            "data": node.state.to_ui_dict()
        }))
        
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)
            await handle_ui_command(message)
    except WebSocketDisconnect:
        pass # Normal disconnection
    except Exception as e:
        # Avoid crashing on unexpected socket errors
        print(f"UI WebSocket error on node {node.config.node_id if node else '?'}: {e}")
    finally:
        # Ensure cleanup even if communication fails
        if node and websocket in node.network.ui_websockets:
            node.network.ui_websockets.remove(websocket)

async def handle_ui_command(cmd: dict):
    if not node:
        return
    action = cmd.get("action")
    if action == "play_card":
        # cmd["card"] is a {rank, suit} dict sent from the frontend
        await node.ui_play_card(cmd["pile_idx"], cmd["card"])
    elif action == "draw_card":
        # Player explicitly draws one card from their private face-down deck
        await node.ui_draw_card()
        await node.network.notify_ui(node.state.to_ui_dict())
    elif action == "shuffle":
        await node.ui_shuffle_deck()
    elif action == "acquire_turn":
        await node.ui_acquire_turn()
    elif action == "release_turn":
        await node.ui_release_turn()
    elif action == "snapshot":
        await node.snapshot_proto.initiate()
    elif action == "distribute_cards":
        await node.ui_distribute_cards()
    elif action == "pass_token":
        await node.token_proto.pass_token()
    elif action == "request_mutex":
        await node.mutex_proto.request_access()
    elif action == "regenerate_token":
        await node.token_proto.regenerate_token()

@app.websocket("/ws/node")
async def websocket_node(websocket: WebSocket):
    await websocket.accept()
    if not node:
        await websocket.close()
        return
    # In this P2P setup, we accept connections from peers.
    try:
        while True:
            data = await websocket.receive_text()
            msg_dict = json.loads(data)
            msg = Message(**msg_dict)
            await node.handle_peer_message(msg)
    except WebSocketDisconnect:
        pass

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True, help="Path to node config JSON")
    parser.add_argument("--peer", action="append", help="Override peer address (e.g., node2=ws://192.168.1.11:7002/ws/node)")
    args = parser.parse_args()

    # Load config file
    config_path = args.config
    if not os.path.isabs(config_path):
        # Try relative to current working directory or script directory
        script_dir = os.path.dirname(os.path.abspath(__file__))
        test_path = os.path.join(script_dir, "..", "..", config_path)
        if os.path.exists(test_path):
            config_path = test_path

    with open(config_path, "r") as f:
        config_data = json.load(f)
        config = NodeConfig(**config_data)

    if args.peer:
        for p_override in args.peer:
            if "=" in p_override:
                nid, url = p_override.split("=", 1)
                config.peers[nid] = url
                print(f"DEBUG: Overriding peer {nid} with {url}")

    global node
    node = Node(config)
    
    uvicorn.run(app, host=config.listen_host, port=config.listen_port)

if __name__ == "__main__":
    main()

