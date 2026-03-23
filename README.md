# 🃏 Multiplayer Card Clash

**A real-time, networked multiplayer card game built on a client-server architecture, enabling seamless and synchronized gameplay across multiple players.**

---

## Overview

Multiplayer Card Clash is a full-stack, real-time multiplayer card game designed to deliver a smooth and interactive gaming experience over a network. The system follows a **client-server architecture**, where one player hosts the server and multiple players connect as clients.

All player actions are transmitted instantly through the server, ensuring **real-time synchronization** and a consistent game state for all participants.

The application is divided into:
- A **Python-based backend** that handles networking, concurrency, and communication.
- A **TypeScript and CSS frontend** that provides an interactive browser-based user interface.

---

## ⚙️ Architecture & Working

### Server (Backend)
- Acts as the central coordinator of the game.
- Listens for incoming connections on a designated port (default: `5000`).
- Uses **multi-threading** to handle multiple clients concurrently.
- Broadcasts player actions and messages to all connected clients in real time.
- Allows the host to send administrative messages directly from the terminal.

### Client
- Connects to the server using its IP address.
- Maintains a continuous connection using sockets.
- Runs a background thread to **asynchronously receive updates**, ensuring uninterrupted gameplay.

### Frontend
- Built using **TypeScript and CSS**.
- Provides a responsive and interactive card game interface.
- Handles user interactions, visual rendering, and gameplay experience in the browser.

---

## Project Structure

```
Multiplayer-Card-Clash/
│
├── card-game/           # Frontend — TypeScript & CSS browser-based game UI
├── sample_server.py     # Backend server — manages connections & broadcasts game events
├── sample_client.py     # Client script — connects a player to the game session
└── README.md
```

---

## Tech Stack

| Layer      | Technology                         |
|------------|------------------------------------|
| Backend    | Python 3, Sockets, Threading       |
| Frontend   | TypeScript, CSS                    |
| Networking | TCP Protocol (web sockets)         |

---

## Key Features

- Real-time multiplayer gameplay
- Client-server architecture with centralized coordination
- Concurrent handling of multiple players using threading
- Instant message broadcasting for synchronized game state
- Lightweight networking using TCP web sockets
- Interactive browser-based UI

---

## Contributors

| Name | GitHub |
|------|--------|
| Devika Unnikrishnan | [DevikaUk](https://github.com/DevikaUk) |
| Krishna Deepak | [krisndeep](https://github.com/krisndeep) |
| Yogini Aishwaryaa P T S | [yoginiaishwaryaa](https://github.com/yoginiaishwaryaa) |

---

## License

This project is licensed under the **MIT License**.
