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

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global node instance
node: Optional[Node] = None

@app.on_event("startup")
async def startup_event():
    if node:
        asyncio.create_task(node.start())

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
    # Send initial state
    await websocket.send_text(json.dumps({
        "type": "STATE_UPDATE", 
        "data": node.state.to_ui_dict()
    }))
    
    try:
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)
            await handle_ui_command(message)
    except WebSocketDisconnect:
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
    elif action == "snapshot":
        await node.snapshot_proto.initiate()
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

    global node
    node = Node(config)
    
    uvicorn.run(app, host=config.listen_host, port=config.listen_port)

if __name__ == "__main__":
    main()

