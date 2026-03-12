# Fantasy Baseball Draft Assistant

Stateless backend + frontend scaffold for live fantasy baseball draft recommendations.

## Repo Structure

```text
fantasy-baseball-draft-assistant/
  backend/
    app/
    tests/
    docs/
    main.py
  frontend/
    src/
    package.json
```

## Backend (FastAPI)

### Run locally

```powershell
cd backend
python -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload
```

Base URL: `http://127.0.0.1:8000`  
Swagger UI: `http://127.0.0.1:8000/docs`

### Test

```powershell
cd backend
python -m pytest -q
```

## API Endpoints

### `POST /api/recommendation`
Get packaged recommendation from current draft state.

### `POST /api/apply-pick`
Apply a pick to state and return updated state.

### `POST /api/recommendation-after-pick`
Apply a pick and return updated state + recomputed recommendation.

## Request Contracts

### Base Draft State Payload

```json
{
  "current_pick": 45,
  "user_slot": 4,
  "teams": 12,
  "drafted_player_ids": ["shohei-ohtani__dh-sp", "aaron-judge__of"],
  "user_roster_player_ids": ["paul-skenes__sp", "austin-riley__3b"],
  "available_player_ids": null,
  "include_debug": false,
  "top_n": 10
}
```

### Apply Pick Payload

```json
{
  "state": { "...": "base draft state payload" },
  "picked_player_id": "corbin-burnes__sp",
  "picked_by_slot": 4,
  "apply_to_user_roster": true,
  "advance_pick": true,
  "include_recommendation": true
}
```

## Response Shapes

### Recommendation

```json
{
  "ok": true,
  "recommendation": {
    "headline_recommendation": {},
    "alternate_recommendations": [],
    "value_falls": [],
    "wait_on_it_candidates": [],
    "risk_flags": [],
    "strategic_explanation": [],
    "draft_context": {},
    "raw_debug": {}
  }
}
```

### Apply Pick

```json
{
  "ok": true,
  "state": {}
}
```

### Recommendation After Pick

```json
{
  "ok": true,
  "state": {},
  "recommendation": {}
}
```

### Error

```json
{
  "ok": false,
  "error": "...",
  "details": "...",
  "debug": {}
}
```

## Frontend (Vite + React)

### Environment

Create `frontend/.env.local`:

```dotenv
VITE_API_BASE_URL=http://127.0.0.1:8000
```

### Run (machine with Node.js installed)

```powershell
cd frontend
npm install
npm run dev
```

Dev URL: `http://localhost:5173`

## CORS

Backend should allow frontend origins:

- `http://localhost:5173`
- `http://127.0.0.1:5173`

## Frontend Handoff Docs

- `backend/docs/frontend_api_handoff.md`
- `backend/docs/openapi_like_spec.json`

## Notes

- Architecture is stateless: frontend owns draft state between calls.
- Use `/api/recommendation-after-pick` as the default route after each pick event.