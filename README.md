# CITS3403 Group Project - Perth Monopoly
## 1. Project Drescription
### Idea suggestion
#### Anthony
- reddit-like msg board with file uploading
#### Shuo Li
- UWA Student Marketplace
- Lost and found system
####
## 2. Group Members
| UWA ID | Name | GitHub Username |
|--------|------|-----------------|
|23903382|Anthony Do|zephris|
|24038633|Shuo Li|DAZAI0336|
|23830475|zhirui chen|zhiruiChen1|

## 3. Application launch

### Dependencies
This project requires Python 3.13 and the following packages:
- Flask
- Flask-SQLAlchemy
- Flask-SocketIO

Optional (recommended for production websocket performance):
- eventlet

### Setup (PowerShell)
1. Create and activate a virtual environment:
	- `python -m venv .venv`
	- `./.venv/Scripts/Activate.ps1`
2. Install dependencies:
	- `./install_deps.sh`
3. Run the app:
	- `python app.py`

### WebSocket Lobby Sync
Multiplayer lobbies use Socket.IO to keep all clients in sync. The flow is:
- The game page embeds `data-lobby-id` and the client connects to Socket.IO.
- Client emits `join_lobby` with the lobby id.
- Server joins the client to room `lobby_<id>`.
- When any player performs an action (roll/buy/skip/build/sell/reset), the server emits `game_state_updated` to the lobby room.
- Each client then calls `/game/<game_id>/state` to render their own personalized HTML.

Events:
- Client -> Server: `join_lobby` `{ lobby_id }`
- Server -> Client: `game_state_updated` `{ game_id }`

## 4. Application testing