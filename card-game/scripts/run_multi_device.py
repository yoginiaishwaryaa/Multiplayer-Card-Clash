import subprocess
import time
import sys
import os
import argparse
import json

def run_node(node_id):
    config_path = f"nodes/{node_id}.json"
    if not os.path.exists(config_path):
        print(f"Error: Config file {config_path} not found.")
        sys.exit(1)
        
    # Load config to get ports
    with open(config_path, "r") as f:
        config = json.load(f)
        backend_port = config.get("listen_port", 7001)
        frontend_port = config.get("ui_port", 3001)

    print(f"--- Starting Node: {node_id} ---")
    
    # 1. Start Backend
    backend_proc = subprocess.Popen(
        [sys.executable, "-m", "backend.app.main", "--config", config_path],
    )
    
    # 2. Start Frontend
    env = os.environ.copy()
    # In distributed mode, the frontend on THIS machine connects to the backend on THIS machine's localhost
    # (since the backend is running locally on this device)
    env["VITE_NODE_UI_WS"] = f"ws://localhost:{backend_port}/ws/ui"
    
    npm_cmd = "npm.cmd" if sys.platform == "win32" else "npm"
    frontend_proc = subprocess.Popen(
        [npm_cmd, "run", "dev", "--", "--port", str(frontend_port), "--host"],
        cwd="frontend",
        env=env
    )
    
    return [backend_proc, frontend_proc]

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run a single node in the distributed card game.")
    parser.add_argument("node_id", help="The node ID to run (e.g., node1, node2, node3)")
    args = parser.parse_args()

    processes = []
    try:
        processes = run_node(args.node_id)
        
        print(f"\nNode {args.node_id} is running!")
        print(f"Open your browser at: http://localhost:[frontend_port]")
        print("Press Ctrl+C to stop.")
        
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nShutting down...")
        for p in processes:
            p.terminate()
            p.wait()
