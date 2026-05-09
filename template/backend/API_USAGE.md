# API Usage Guide

Base URL (local): <[http://127.0.0.1:5000](http://127.0.0.1:5000 "‌")\> (dynamic update with getenv for deployment ip)

All endpoints that require authentication use the Flask session cookie from \`/auth/login\`.

Related schema docs: see here(to insert link for database schema).

#  Auth

## Registration

- Method/Path: \`POST /auth/register\`
  \- Body:

```json
{
  "username": "player1",
  "password": "strong-password"
}
```

- Success: `201`
- Common errors: `400` (missing username/password), `409` (username exists)

### Login

- Method/Path: `POST /auth/login`
- Body:

```json
{
  "username": "player1",
  "password": "strong-password"
}
```

- Success: `200`, set session cookie for client session.
- Common errors: `401` (invalid credenticdals)

### Logout

- Method/Path: `POST /auth/logout`
- Success: `200,`remove session cookie for client session.
- Common errors: `401` (not logged in)

### Current User

- Method/Path: `GET /auth/me`
- Success: `200`, check current user session status
- Common errors: `401` (not logged in)

## Lobbies

### Create Lobby

- Method/Path: `POST /lobbies`
- Body:

```json
{
  "lobby_type": "public",
  "name": "Friday Night Game",
  "max_players": 4
}
```

- Notes:
- `lobby_type` supports `public`, `private`, `single`
- `max_players` is clamped to `2..4` for multiplayer and forced to `1` for single-player
- Success: `201`
- Returns: `lobby_id`, `lobby_type`, `name`, `invite_code`, `max_players`
- Common errors: `400` (invalid lobby_type or malformed payload), `401` (not logged in)

### List Public Lobbies

- Method/Path: `GET /lobbies/public`
- Success: `200`
- Returns: list of open public lobbies with host username and current player count
- Common errors: `401` (not logged in)

### Join Lobby by ID

- Method/Path: `POST /lobbies/{lobby_id}/join`
- Success: `200`
- Common errors: `401` (not logged in), `404` (lobby missing), `409` (lobby closed/full)

### Join Private Lobby by Code

- Method/Path: `POST /lobbies/join-by-code`
- Body:

```json
{
  "invite_code": "AB12CD34"
}
```

- Success: `200`
- Common errors: `400` (missing code), `401` (not logged in), `404` (code not found), `403` (lobby closed/full)

### Leave Lobby

- Method/Path: `POST /lobbies/{lobby_id}/leave`
- Success: `200`
- Common errors: `401` (not logged in), `404` (membership/lobby missing)

### Set Ready State

- Method/Path: `POST /lobbies/{lobby_id}/ready`
- Body:

```json
{
  "ready": true
}
```

- Success: `200`
- Common errors: `401` (not logged in), `404` (membership/lobby missing)

### Start Game

- Method/Path: `POST /lobbies/{lobby_id}/start`
- Rules:
  - host only
  - single-player requires exactly 1 player
  - multiplayer requires at least 2 players, all ready
  - multiplayer can start with fewer than 4 players
- Success: `200`
- Returns: `message`, `lobby_id`, `game_id`
- Common errors: `401` (not logged in), `403` (not host), `404` (lobby missing), `409` (validation failed)

## Profiles

### My Profile

- Method/Path: `GET /profiles/me`
- Success: `200`
- Returns: profile object + stats object
- Common errors: `401` (not logged in)

### Update My Profile

- Method/Path: `PATCH /profiles/me`
- Body:

```json
{
  "is_public": true,
  "bio": "Landlord of Perth"
}
```

- Success: `200`
- Common errors: `400` (no fields), `401` (not logged in), `404` (user missing)

### View User Profile

- Method/Path: `GET /profiles/{user_id}`
- Notes:
- private profiles are hidden from other users
- Success: `200`
- Common errors: `401` (not logged in), `403` (private profile), `404` (user missing)

## Stats

### Record In-Game Event

- Timed event (for player turn time)
- Method/Path: `POST /stats/events`
- Body(example event):

```json
{
  "game_id": [game id],
  "event_type": [event type string],
  "amount": [int],
  "metadata": {
    "from_user_id": [pid]
    "to_user_id": [pid]
  }
}
```

- Success: `201`
- Common errors: `400` (missing required fields), `401` (not logged in), `403` (not in game), `404` (game missing), `409` (game not in progress)

### Finalize Game

- Method/Path: `POST /stats/games/{game_id}/finalize`
- Body:

```json
{
  "winner_user_id": 1,
  "player_results": [
    {
      "user_id": 1,
      "final_rank": 1,
      "bankrupt_flag": false,
      "turns_taken": 42
    },
    {
      "user_id": 2,
      "final_rank": 2,
      "bankrupt_flag": true,
      "turns_taken": 39
    }
  ]
}
```

- Success: `200`
- Common errors: `400` (invalid payload), `401` (not logged in), `403` (not host), `404` (game missing), `409` (already finalized)

## Leaderboard

### Get Leaderboard

- Method/Path: `GET /leaderboard?sort_by=wins&limit=50&min_games=1`
- `sort_by` supports: `wins`, `net_worth`, `win_rate`
- Success: `200`
- Returns: public profiles only, sorted by selected metric

## Scheduled Data Retention

- A background retention job runs automatically and removes completed game data older than 1 week by default.
- Purged tables: `game_sessions`, `game_player_state`, `transaction_events`
- Preserved table: `player_stats` (aggregated totals remain available)
- Config knobs in app config:
- `RETENTION_ENABLED`
- `RETENTION_DAYS`
- `RETENTION_INTERVAL_HOURS`
- `RETENTION_RUN_ON_STARTUP`

## Example cURL Flow

```bash
# 1) Register
curl -i -X POST http://[remote]/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username":"player1","password":"secret"}'

# 2) Login and persist cookie
curl -i -c cookies.txt -X POST http://[remote]/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"player1","password":"secret"}'

# 3) Create lobby with auth cookie
curl -i -b cookies.txt -X POST http://[remote]/lobbies \
  -H "Content-Type: application/json" \
  -d '{"lobby_type":"public","name":"Weekend Match","max_players":4}'
```
