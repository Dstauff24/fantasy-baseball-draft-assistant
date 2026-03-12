# Fantasy Baseball Draft Assistant — Frontend API Handoff

## Architecture

The backend is **fully stateless**. Every request contains the full current draft
state. The backend applies any mutations (picks), recomputes recommendations, and
returns the updated state + result in one response.

There is no session storage, authentication, or persistent draft state on the
server. The frontend owns state between calls.

---

## Base URL

```
http://localhost:8000
```

---

## Routes

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/recommendation` | Get recommendation from current draft state |
| POST | `/api/apply-pick` | Apply a pick, return updated state only |
| POST | `/api/recommendation-after-pick` | Apply a pick + return updated state and recommendation |

---

## Base Draft State Payload

Every route uses this payload shape (directly or as `state` in apply-pick operations).

```json
{
  "current_pick": 45,
  "user_slot": 4,
  "teams": 12,
  "drafted_player_ids": [
    "shohei-ohtani__dh-sp",
    "aaron-judge__of"
  ],
  "user_roster_player_ids": [
    "paul-skenes__sp",
    "austin-riley__3b"
  ],
  "available_player_ids": null,
  "top_n": 10,
  "include_debug": false
}
```

### Field Reference

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `current_pick` | int | ✅ | Current overall pick number (1-indexed) |
| `user_slot` | int | ✅ | User's draft slot (1–teams) |
| `teams` | int | ✅ | Total teams in league |
| `drafted_player_ids` | string[] | ✅ | All player IDs drafted so far, in order |
| `user_roster_player_ids` | string[] | ✅ | Player IDs on user's roster |
| `available_player_ids` | string[] \| null | ❌ | If null, backend infers from projection pool |
| `top_n` | int | ❌ | Max candidates to return (default: 10) |
| `include_debug` | bool | ❌ | If true, include internal debug trace (dev only) |
| `projections_csv_path` | string | ❌ | Dev-only: local path to projections CSV |

---

## POST /api/recommendation

Get a packaged recommendation for the current draft state.

### Request

```json
{
  "current_pick": 45,
  "user_slot": 4,
  "teams": 12,
  "drafted_player_ids": ["shohei-ohtani__dh-sp", "aaron-judge__of"],
  "user_roster_player_ids": ["paul-skenes__sp", "austin-riley__3b"],
  "available_player_ids": null,
  "top_n": 10,
  "include_debug": false
}
```

### Success Response

```json
{
  "ok": true,
  "recommendation": {
    "headline_recommendation": {
      "player_id": "corbin-burnes__sp",
      "player_name": "Corbin Burnes",
      "team": "ARI",
      "positions": ["SP"],
      "draft_score": 0.87,
      "survival_probability": 0.81,
      "board_pressure_score": 0.72,
      "reasoning": ["High strikeout rate", "Scarce SP window closing"]
    },
    "alternate_recommendations": [ ... ],
    "value_falls": [ ... ],
    "wait_on_it_candidates": [ ... ],
    "risk_flags": [ ... ],
    "strategic_explanation": [ ... ],
    "draft_context": {
      "current_pick": 45,
      "next_user_pick": 52,
      "teams_until_next_pick": 6,
      "roster_snapshot": {
        "count": 2,
        "players": ["Paul Skenes", "Austin Riley"],
        "positions": ["SP", "3B"]
      },
      "positional_pressure": { ... },
      "likely_run_positions": ["SP", "OF"]
    }
  }
}
```

---

## POST /api/apply-pick

Apply one pick to the board and return the updated draft state.
Does **not** recompute recommendation unless `include_recommendation: true`.

### Request

```json
{
  "state": {
    "current_pick": 45,
    "user_slot": 4,
    "teams": 12,
    "drafted_player_ids": ["shohei-ohtani__dh-sp", "aaron-judge__of"],
    "user_roster_player_ids": ["paul-skenes__sp", "austin-riley__3b"],
    "available_player_ids": null,
    "top_n": 10
  },
  "picked_player_id": "julio-rodriguez__of",
  "picked_by_slot": 5,
  "apply_to_user_roster": false,
  "advance_pick": true,
  "include_recommendation": false
}
```

### Field Reference (apply-pick specific)

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `state` | DraftStatePayload | ✅ | Current draft state |
| `picked_player_id` | string | ✅ | Player ID just drafted |
| `picked_by_slot` | int | ❌ | Which slot drafted (for tracking) |
| `apply_to_user_roster` | bool | ❌ | Add player to user roster (default: false) |
| `advance_pick` | bool | ❌ | Increment current_pick by 1 (default: true) |
| `include_recommendation` | bool | ❌ | Also compute recommendation (default: false) |

### Success Response

```json
{
  "ok": true,
  "state": {
    "current_pick": 46,
    "user_slot": 4,
    "teams": 12,
    "drafted_player_ids": [
      "shohei-ohtani__dh-sp",
      "aaron-judge__of",
      "julio-rodriguez__of"
    ],
    "user_roster_player_ids": ["paul-skenes__sp", "austin-riley__3b"],
    "available_player_ids": null,
    "top_n": 10
  }
}
```

---

## POST /api/recommendation-after-pick

Apply a pick **and** immediately return updated state + recomputed recommendation.
This is the primary route for live draft board updates.

### Request

Same shape as `/api/apply-pick`. Backend always forces `include_recommendation: true`.

```json
{
  "state": {
    "current_pick": 45,
    "user_slot": 4,
    "teams": 12,
    "drafted_player_ids": ["shohei-ohtani__dh-sp", "aaron-judge__of"],
    "user_roster_player_ids": ["paul-skenes__sp", "austin-riley__3b"],
    "available_player_ids": null,
    "top_n": 10
  },
  "picked_player_id": "corbin-burnes__sp",
  "picked_by_slot": 4,
  "apply_to_user_roster": true,
  "advance_pick": true
}
```

### Success Response

```json
{
  "ok": true,
  "state": {
    "current_pick": 46,
    "drafted_player_ids": [
      "shohei-ohtani__dh-sp",
      "aaron-judge__of",
      "corbin-burnes__sp"
    ],
    "user_roster_player_ids": [
      "paul-skenes__sp",
      "austin-riley__3b",
      "corbin-burnes__sp"
    ]
  },
  "recommendation": { ... }
}
```

---

## Error Response

All routes return this shape on failure:

```json
{
  "ok": false,
  "error": "Invalid live draft operation",
  "details": "picked_player_id is required"
}
```

With `include_debug: true`:

```json
{
  "ok": false,
  "error": "Invalid recommendation request",
  "details": "current_pick is required",
  "debug": {
    "failed_stage": "parse_request",
    "exception_type": "RecommendationRequestValidationError",
    "events": [ ... ]
  }
}
```

---

## Recommended Frontend Call Flow

```
1. On draft start:
   → Build initial DraftStatePayload
   → POST /api/recommendation
   → Display headline + alternates + draft_context

2. After each non-user board pick:
   → POST /api/recommendation-after-pick
     { state: currentState, picked_player_id, picked_by_slot, apply_to_user_roster: false }
   → Update currentState = response.state
   → Refresh recommendation display

3. When user makes a pick:
   → POST /api/recommendation-after-pick
     { state: currentState, picked_player_id, picked_by_slot: user_slot, apply_to_user_roster: true }
   → Update currentState = response.state
   → Refresh recommendation display + roster snapshot
```

---

## UI Component Mapping

| Response field | Suggested UI component |
|----------------|----------------------|
| `headline_recommendation` | Hero card — primary pick suggestion |
| `alternate_recommendations` | Scrollable alternate cards row |
| `value_falls` | Value alert panel — players dropping |
| `wait_on_it_candidates` | Patience queue — safe to wait |
| `risk_flags` | Warning badges on player cards |
| `strategic_explanation` | Contextual strategy text / tooltip |
| `draft_context.current_pick` | Pick counter in header |
| `draft_context.next_user_pick` | "Your next pick" indicator |
| `draft_context.teams_until_next_pick` | Urgency timer/bar |
| `draft_context.roster_snapshot` | User roster sidebar |
| `draft_context.likely_run_positions` | Position run alert bar |

---

## Debug Mode (Development Only)

Add `"include_debug": true` to any request payload.

The response will include a `debug` object with:
- stage-by-stage trace events
- exception type and message on failure
- internal scoring details under `raw_debug`

**Do not expose debug output in production UI.**

---

## Player ID Format

Player IDs follow the pattern:

```
{first-last}__{position}
```

Examples:
- `shohei-ohtani__dh-sp`
- `paul-skenes__sp`
- `austin-riley__3b`

Use these IDs consistently across `drafted_player_ids`, `user_roster_player_ids`,
and `picked_player_id`.

---

## OpenAPI Specification

This API is documented using OpenAPI 3.0.0. The full specification is available
at [http://localhost:8000/api-docs](http://localhost:8000/api-docs).

### OpenAPI Document

{
  "openapi": "3.0.0",
  "info": {
    "title": "Fantasy Baseball Draft Assistant API",
    "version": "1.0.0",
    "description": "Stateless live-draft recommendation API for fantasy baseball."
  },
  "servers": [
    { "url": "http://localhost:8000", "description": "Local development" }
  ],
  "paths": {
    "/api/recommendation": {
      "post": {
        "summary": "Get recommendation from current draft state",
        "requestBody": {
          "required": true,
          "content": {
            "application/json": {
              "schema": { "$ref": "#/components/schemas/DraftStatePayload" },
              "example": {
                "current_pick": 45,
                "user_slot": 4,
                "teams": 12,
                "drafted_player_ids": ["shohei-ohtani__dh-sp", "aaron-judge__of"],
                "user_roster_player_ids": ["paul-skenes__sp", "austin-riley__3b"],
                "available_player_ids": null,
                "top_n": 10,
                "include_debug": false
              }
            }
          }
        },
        "responses": {
          "200": {
            "description": "Packaged recommendation response",
            "content": {
              "application/json": {
                "schema": { "$ref": "#/components/schemas/RecommendationResponse" }
              }
            }
          }
        }
      }
    },
    "/api/apply-pick": {
      "post": {
        "summary": "Apply a board pick and return updated draft state",
        "requestBody": {
          "required": true,
          "content": {
            "application/json": {
              "schema": { "$ref": "#/components/schemas/ApplyPickPayload" },
              "example": {
                "state": {
                  "current_pick": 45,
                  "user_slot": 4,
                  "teams": 12,
                  "drafted_player_ids": ["shohei-ohtani__dh-sp", "aaron-judge__of"],
                  "user_roster_player_ids": ["paul-skenes__sp", "austin-riley__3b"],
                  "available_player_ids": null,
                  "top_n": 10
                },
                "picked_player_id": "julio-rodriguez__of",
                "picked_by_slot": 5,
                "apply_to_user_roster": false,
                "advance_pick": true,
                "include_recommendation": false
              }
            }
          }
        },
        "responses": {
          "200": {
            "description": "Updated draft state",
            "content": {
              "application/json": {
                "schema": { "$ref": "#/components/schemas/ApplyPickResponse" }
              }
            }
          }
        }
      }
    },
    "/api/recommendation-after-pick": {
      "post": {
        "summary": "Apply a pick and return updated state + recomputed recommendation",
        "description": "Primary route for live draft board updates after each pick. Always recomputes recommendation.",
        "requestBody": {
          "required": true,
          "content": {
            "application/json": {
              "schema": { "$ref": "#/components/schemas/ApplyPickPayload" },
              "example": {
                "state": {
                  "current_pick": 45,
                  "user_slot": 4,
                  "teams": 12,
                  "drafted_player_ids": ["shohei-ohtani__dh-sp", "aaron-judge__of"],
                  "user_roster_player_ids": ["paul-skenes__sp", "austin-riley__3b"],
                  "available_player_ids": null,
                  "top_n": 10
                },
                "picked_player_id": "corbin-burnes__sp",
                "picked_by_slot": 4,
                "apply_to_user_roster": true,
                "advance_pick": true
              }
            }
          }
        },
        "responses": {
          "200": {
            "description": "Updated state and packaged recommendation",
            "content": {
              "application/json": {
                "schema": { "$ref": "#/components/schemas/RecommendationAfterPickResponse" }
              }
            }
          }
        }
      }
    }
  },
  "components": {
    "schemas": {
      "DraftStatePayload": {
        "type": "object",
        "required": ["current_pick", "user_slot", "teams"],
        "properties": {
          "current_pick":            { "type": "integer", "description": "Current overall pick number (1-indexed)" },
          "user_slot":               { "type": "integer", "description": "User's draft slot (1 to teams)" },
          "teams":                   { "type": "integer", "description": "Total number of teams in league" },
          "drafted_player_ids":      { "type": "array", "items": { "type": "string" }, "description": "All drafted player IDs in order" },
          "user_roster_player_ids":  { "type": "array", "items": { "type": "string" }, "description": "Player IDs on user's roster" },
          "available_player_ids":    { "type": ["array", "null"], "items": { "type": "string" }, "description": "Available board (null = infer from pool)" },
          "top_n":                   { "type": "integer", "default": 10, "description": "Max candidates to return" },
          "include_debug":           { "type": "boolean", "default": false, "description": "Include debug trace in response (dev only)" },
          "projections_csv_path":    { "type": "string", "description": "Dev-only: local path to projections CSV" }
        }
      },
      "ApplyPickPayload": {
        "type": "object",
        "required": ["state", "picked_player_id"],
        "properties": {
          "state":                  { "$ref": "#/components/schemas/DraftStatePayload" },
          "picked_player_id":       { "type": "string", "description": "Player ID just drafted" },
          "picked_by_slot":         { "type": "integer", "description": "Draft slot that made the pick" },
          "apply_to_user_roster":   { "type": "boolean", "default": false, "description": "Add player to user roster" },
          "advance_pick":           { "type": "boolean", "default": true, "description": "Increment current_pick by 1" },
          "include_recommendation": { "type": "boolean", "default": false, "description": "Recompute recommendation after pick" }
        }
      },
      "RecommendationResponse": {
        "type": "object",
        "properties": {
          "ok":             { "type": "boolean" },
          "recommendation": { "$ref": "#/components/schemas/RecommendationPayload" }
        }
      },
      "ApplyPickResponse": {
        "type": "object",
        "properties": {
          "ok":    { "type": "boolean" },
          "state": { "$ref": "#/components/schemas/DraftStatePayload" }
        }
      },
      "RecommendationAfterPickResponse": {
        "type": "object",
        "properties": {
          "ok":             { "type": "boolean" },
          "state":          { "$ref": "#/components/schemas/DraftStatePayload" },
          "recommendation": { "$ref": "#/components/schemas/RecommendationPayload" }
        }
      },
      "RecommendationPayload": {
        "type": "object",
        "properties": {
          "headline_recommendation":  { "$ref": "#/components/schemas/PlayerCard" },
          "alternate_recommendations":{ "type": "array", "items": { "$ref": "#/components/schemas/PlayerCard" } },
          "value_falls":              { "type": "array", "items": { "$ref": "#/components/schemas/PlayerCard" } },
          "wait_on_it_candidates":    { "type": "array", "items": { "$ref": "#/components/schemas/PlayerCard" } },
          "risk_flags":               { "type": "array", "items": { "type": "object" } },
          "strategic_explanation":    { "type": "array", "items": { "type": "string" } },
          "draft_context":            { "$ref": "#/components/schemas/DraftContextSummary" },
          "raw_debug":                { "type": "object", "description": "Present only when include_debug=true" }
        }
      },
      "PlayerCard": {
        "type": "object",
        "properties": {
          "player_id":             { "type": "string" },
          "player_name":           { "type": "string" },
          "team":                  { "type": "string" },
          "positions":             { "type": "array", "items": { "type": "string" } },
          "draft_score":           { "type": "number" },
          "survival_probability":  { "type": "number" },
          "board_pressure_score":  { "type": "number" },
          "reasoning":             { "type": "array", "items": { "type": "string" } }
        }
      },
      "DraftContextSummary": {
        "type": "object",
        "properties": {
          "current_pick":           { "type": "integer" },
          "next_user_pick":         { "type": ["integer", "null"] },
          "teams_until_next_pick":  { "type": "integer" },
          "roster_snapshot": {
            "type": "object",
            "properties": {
              "count":     { "type": "integer" },
              "players":   { "type": "array", "items": { "type": "string" } },
              "positions": { "type": "array", "items": { "type": "string" } }
            }
          },
          "positional_pressure":   { "type": "object" },
          "likely_run_positions":  { "type": "array", "items": { "type": "string" } }
        }
      },
      "ErrorResponse": {
        "type": "object",
        "properties": {
          "ok":      { "type": "boolean", "enum": [false] },
          "error":   { "type": "string" },
          "details": { "type": "string" },
          "debug":   { "type": "object", "description": "Present only when include_debug=true" }
        }
      }
    }
  }
}