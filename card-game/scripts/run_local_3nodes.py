import subprocess
import time
import sys
import os

def run_node(node_id, port):
    config_path = f"nodes/{node_id}.json"
    return subprocess.Popen(
        [sys.executable, "-m", "backend.app.main", "--config", config_path],
        # cwd=os.getcwd()
    )

def run_frontend(port, backend_port):
    env = os.environ.copy()
    env["VITE_NODE_UI_WS"] = f"ws://localhost:{backend_port}/ws/ui"
    # On Windows, npm is a .cmd script, so we must use "npm.cmd"
    npm_cmd = "npm.cmd" if sys.platform == "win32" else "npm"
    return subprocess.Popen(
        [npm_cmd, "run", "dev", "--", "--port", str(port)],
        cwd="frontend",
        env=env
    )

if __name__ == "__main__":
    processes = []
    try:
        print("Starting 3 Python Nodes...")
        processes.append(run_node("node1", 7001))
        processes.append(run_node("node2", 7002))
        processes.append(run_node("node3", 7003))
        
        time.sleep(2) # Give backends a moment
        
        print("Starting 3 React Frontends...")
        processes.append(run_frontend(3001, 7001))
        processes.append(run_frontend(3002, 7002))
        processes.append(run_frontend(3003, 7003))
        
        print("\nAll nodes running!")
        print("Node 1: http://localhost:3001")
        print("Node 2: http://localhost:3002")
        print("Node 3: http://localhost:3003")
        print("\nPress Ctrl+C to stop all.")
        
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nShutting down...")
        for p in processes:
            p.terminate()
