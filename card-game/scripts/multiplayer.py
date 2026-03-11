import subprocess
import time
import sys
import os
import argparse
import json
import socket

def get_network_config():
    """Load the central network configuration."""
    config_path = "nodes/network_config.json"
    if not os.path.exists(config_path):
        # Create default if missing
        default = {"node1": "localhost", "node2": "localhost", "node3": "localhost"}
        with open(config_path, "w") as f:
            json.dump(default, f, indent=4)
        return default
    with open(config_path, "r") as f:
        return json.load(f)

def run_node(node_id, network_config):
    config_path = f"nodes/{node_id}.json"
    if not os.path.exists(config_path):
        print(f"Error: Config file {config_path} not found.")
        return None
        
    cmd = [sys.executable, "-m", "backend.app.main", "--config", config_path]
    
    # Inject peer URLs based on network_config.json
    for nid, ip in network_config.items():
        if nid != node_id:
            # Ports are 7001, 7002, 7003 corresponding to node1, node2, node3
            port = 7000 + int(nid.replace("node", ""))
            url = f"ws://{ip}:{port}/ws/node"
            cmd.extend(["--peer", f"{nid}={url}"])

    print(f"--- Starting Backend: {node_id} ---")
    return subprocess.Popen(cmd)

def run_frontend(node_id, network_config):
    config_path = f"nodes/{node_id}.json"
    if not os.path.exists(config_path):
        return None
        
    with open(config_path, "r") as f:
        config = json.load(f)
        backend_port = config.get("listen_port", 7001)
        ui_port = config.get("ui_port", 3001)

    print(f"--- Starting Frontend: {node_id} on port {ui_port} ---")
    
    # Use the IP defined in network_config.json for THIS node
    local_backend_ip = network_config.get(node_id, "localhost")
    
    env = os.environ.copy()
    env["VITE_NODE_UI_WS"] = f"ws://{local_backend_ip}:{backend_port}/ws/ui"
    
    npm_cmd = "npm.cmd" if sys.platform == "win32" else "npm"
    return subprocess.Popen(
        [npm_cmd, "run", "dev", "--", "--port", str(ui_port)],
        cwd="frontend",
        env=env
    )

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the Distributed Card Game.")
    parser.add_argument("mode", choices=["local", "device1", "device2", "device3"], 
                        help="Run everything locally, or just a specific node for multi-device setup.")
    args = parser.parse_args()

    # Load centralized IPs from the JSON file the user maintains
    network_config = get_network_config()
    print(f"Loaded Network Configuration from nodes/network_config.json")

    processes = []
    try:
        if args.mode == "local":
            print("Starting all 3 nodes locally (overriding to localhost)...")
            # Force localhost for all nodes in local mode
            local_config = {k: "localhost" for k in network_config.keys()}
            for i in range(1, 4):
                node_name = f"node{i}"
                p_be = run_node(node_name, local_config)
                if p_be: processes.append(p_be)
            
            time.sleep(2)
            
            for i in range(1, 4):
                node_name = f"node{i}"
                p_fe = run_frontend(node_name, local_config)
                if p_fe: processes.append(p_fe)
                
            print("\nAll nodes running locally!")
            print("Node 1: http://localhost:3001")
            print("Node 2: http://localhost:3002")
            print("Node 3: http://localhost:3003")
            
        else:
            # Single node mode for multi-device (device1, device2, device3)
            node_id = args.mode.replace("device", "node")
            
            # Start backend with peer IPs from network_config.json
            p_be = run_node(node_id, network_config)
            if p_be: processes.append(p_be)
            
            time.sleep(1)
            
            # Start frontend
            p_fe = run_frontend(node_id, network_config)
            if p_fe: processes.append(p_fe)
            
            print(f"\n{node_id} is running using IPs from nodes/network_config.json!")

        print("\nPress Ctrl+C to stop.")
        while True:
            time.sleep(1)
            
    except KeyboardInterrupt:
        print("\nShutting down...")
        for p in processes:
            p.terminate()
            p.wait()
