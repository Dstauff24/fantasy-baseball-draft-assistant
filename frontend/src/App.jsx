import { useState } from "react";
import { getRecommendation, applyPick, recommendationAfterPick } from "./api";

const initialState = {
  current_pick: 45,
  user_slot: 4,
  teams: 12,
  drafted_player_ids: ["shohei-ohtani__util", "aaron-judge__of"],
  user_roster_player_ids: ["paul-skenes__sp", "austin-riley__3b"],
  available_player_ids: null,
  include_debug: false,
  top_n: 10
};

export default function App() {
  const [state, setState] = useState(initialState);
  const [pickedPlayerId, setPickedPlayerId] = useState("julio-rodriguez__of");
  const [pickedBySlot, setPickedBySlot] = useState(5);
  const [applyToUserRoster, setApplyToUserRoster] = useState(false);
  const [response, setResponse] = useState(null);
  const [loading, setLoading] = useState(false);

  async function run(action) {
    setLoading(true);
    try {
      let result;
      if (action === "recommendation") {
        result = await getRecommendation(state);
      } else {
        const payload = {
          state,
          picked_player_id: pickedPlayerId,
          picked_by_slot: Number(pickedBySlot),
          apply_to_user_roster: applyToUserRoster,
          advance_pick: true,
          include_recommendation: action === "after-pick"
        };
        result =
          action === "apply-pick"
            ? await applyPick(payload)
            : await recommendationAfterPick(payload);

        if (result?.ok && result?.state) {
          setState(result.state);
        }
      }
      setResponse(result);
    } catch (e) {
      setResponse({ ok: false, error: "Network error", details: String(e) });
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="container">
      <h1>Fantasy Baseball Draft Assistant</h1>
      <p className="muted">Backend: {import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000"}</p>

      <section className="card">
        <h2>Draft State (editable JSON)</h2>
        <textarea
          rows={14}
          value={JSON.stringify(state, null, 2)}
          onChange={(e) => {
            try {
              setState(JSON.parse(e.target.value));
            } catch {
              // ignore until valid json
            }
          }}
        />
        <div className="row">
          <button disabled={loading} onClick={() => run("recommendation")}>
            POST /api/recommendation
          </button>
        </div>
      </section>

      <section className="card">
        <h2>Apply Pick</h2>
        <div className="row">
          <label>picked_player_id</label>
          <input value={pickedPlayerId} onChange={(e) => setPickedPlayerId(e.target.value)} />
        </div>
        <div className="row">
          <label>picked_by_slot</label>
          <input
            type="number"
            value={pickedBySlot}
            onChange={(e) => setPickedBySlot(e.target.value)}
          />
        </div>
        <div className="row">
          <label>apply_to_user_roster</label>
          <input
            type="checkbox"
            checked={applyToUserRoster}
            onChange={(e) => setApplyToUserRoster(e.target.checked)}
          />
        </div>
        <div className="row">
          <button disabled={loading} onClick={() => run("apply-pick")}>
            POST /api/apply-pick
          </button>
          <button disabled={loading} onClick={() => run("after-pick")}>
            POST /api/recommendation-after-pick
          </button>
        </div>
      </section>

      <section className="card">
        <h2>Response</h2>
        <pre>{JSON.stringify(response, null, 2)}</pre>
      </section>
    </div>
  );
}