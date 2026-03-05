# Speed Distributed: Card Game Demo

A distributed systems demonstration featuring:
1. **Token Ring** for special action permissions.
2. **Ricart-Agrawala Mutual Exclusion** for shared resource access (playing cards).
3. **Chandy-Lamport Snapshot Algorithm** for consistent global state capture.

## Setup

### Prerequisites
- Python 3.11+
- Node.js 18+

### Installation
1. Install Backend Dependencies:
   ```bash
   cd backend
   pip install -r requirements.txt
   cd ..
   ```
2. Install Frontend Dependencies:
   ```bash
   cd frontend
   npm install
   cd ..
   ```

## Running the Demo

### 1. Single-Laptop (3 Nodes)
Run the automated script:
```bash
python scripts/run_local_3nodes.py
```
This starts 3 Python nodes on ports 7001-7003 and 3 Vite dev servers on ports 3001-3003.

### 2. Multi-Laptop Operation
1. **Identify LAN IPs**: Get the local IP of each laptop (e.g., `192.168.1.10`, `192.168.1.11`).
2. **Edit Configs**: Update `nodes/nodeX.json` on each machine.
   - Set `peers` to the real IP/Ports of other laptops.
   - Example: For Laptop 1 (node1) connecting to Laptop 2 (node2):
     `"node2": "ws://192.168.1.11:7002/ws/node"`
3. **Run Backend**:
   `python -m backend.app.main --config nodes/node1.json`
4. **Run Frontend**:
   `cd frontend && npm run dev -- --port 3000`
   Ensure your `.env` or run command has: `VITE_NODE_UI_WS=ws://localhost:7001/ws/ui`

## Distributed Algorithms in Play

### Token Ring
- A token circulates among nodes.
- Only the holder can "Reset Piles".
- Watch the **TOKEN** badge and logs.

### Ricart-Agrawala Mutex
- When you click a center pile to play a card, the node requests a distributed lock.
- It broadcasts `MUTEX_REQUEST`, waits for `MUTEX_REPLY` from all peers.
- This ensures no two nodes update the center pile simultaneously.

### Chandy-Lamport Snapshot
- Click "Take Snapshot" on any node.
- It sends `MARKER` messages and records local state + in-transit messages.
- Once complete, a global state view is displayed.

## Troubleshooting
- **Firewall**: Ensure ports 7001-7006 are open on your local network.
- **WebSocket Timeout**: If peers don't connect, check IP addresses and reachability (ping).
- **CORS**: The backend allows all origins by default for this demo.
