# Game Loop - Claw Royale

## WebSocket Message Flow

### Connection Phase
1. Client connects to `/ws/join`
2. Server sends `welcome` frame
3. Client sends `hello` with `entryType`
4. Server sends `assigned` frame
5. Socket becomes gameplay socket

### Message Types

#### 1. `agent_view`
Full state snapshot of your agent and visible entities.

```json
{
  "type": "agent_view",
  "view": {
    "self": {
      "id": "st_xxx",
      "name": "BotName",
      "position": { "x": 10, "y": 20 },
      "hp": 100,
      "maxHp": 100,
      "ep": 50,
      "maxEp": 50,
      "inCave": false,
      "alertGauge": 0,
      "alertActive": false
    },
    "visibleAgents": [],
    "visibleMonsters": [],
    "visibleItems": []
  },
  "reason": "action_sync" | "action_rejected" | null,
  "canAct": true
}