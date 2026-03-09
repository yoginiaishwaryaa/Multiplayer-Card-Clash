import subprocess
import time
import sys
import os

def run_node(config_path):
    return subprocess.Popen([sys.executable, "-m", "backend.app.main", "--config", config_path])

def run_frontend(port, backend_port):
    env = os.environ.copy()
    env["VITE_NODE_UI_WS"] = f"ws://localhost:{backend_port}/ws/ui"
    npm_cmd = "npm.cmd" if sys.platform == "win32" else "npm"
    return subprocess.Popen([npm_cmd, "run", "dev", "--", "--port", str(port)], cwd="frontend", env=env)

if __name__ == "__main__":
    processes = []
    try:
        print("Starting 2 Backend Nodes...")
        processes.append(run_node("nodes/2player_node1.json"))
        processes.append(run_node("nodes/2player_node2.json"))
        
        time.sleep(2)
        
        print("Starting 2 React Frontends...")
        processes.append(run_frontend(3001, 8001))
        processes.append(run_frontend(3002, 8002))
        
        print("\n2-Player Local Demo Running!")
        print("Node 1: http://localhost:3001")
        print("Node 2: http://localhost:3002")
        print("\nPress Ctrl+C to stop all.")
        
        for p in processes:
            p.wait()
    except KeyboardInterrupt:
        print("\nStopping...")
        for p in processes:
            p.terminate()
