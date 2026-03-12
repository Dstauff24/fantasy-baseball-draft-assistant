import { useState } from "react";
import { getRecommendation, applyPick, recommendationAfterPick } from "./api";
import {
  getPrimaryRecommendation,
  getAlternates,
  getValueFalls,
  getWaitOnIt,
  getDraftContext,
} from "./utils/selectors";

import TopBar from "./components/TopBar";
import RecommendationCard from "./components/RecommendationCard";
import RecommendationLists from "./components/RecommendationLists";
import RosterPanel from "./components/RosterPanel";
import DraftControls from "./components/DraftControls";
import PickEntry from "./components/PickEntry";
import DebugDrawer from "./components/DebugDrawer";

const initialState = {
  current_pick: 45,
  user_slot: 4,
  teams: 12,
  drafted_player_ids: ["shohei-ohtani__util", "aaron-judge__of"],
  user_roster_player_ids: ["paul-skenes__sp", "austin-riley__3b"],
  available_player_ids: null,
  include_debug: false,
  top_n: 10,
};

export default function App() {
  const [state, setState] = useState(initialState);
  const [stateText, setStateText] = useState(JSON.stringify(initialState, null, 2));
  const [stateJsonError, setStateJsonError] = useState("");

  const [pickedPlayerId, setPickedPlayerId] = useState("julio-rodriguez__of");
  const [pickedBySlot, setPickedBySlot] = useState(5);
  const [applyToUserRoster, setApplyToUserRoster] = useState(false);

  const [topN, setTopN] = useState(10);
  const [includeDebug, setIncludeDebug] = useState(false);

  const [response, setResponse] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [debugOpen, setDebugOpen] = useState(false);

  function parseStateText() {
    try {
      const parsed = JSON.parse(stateText);
      setStateJsonError("");
      return { ...parsed, top_n: topN, include_debug: includeDebug };
    } catch {
      setStateJsonError("Invalid JSON in draft state");
      return null;
    }
  }

  async function handleRecommendation() {
    const payload = parseStateText();
    if (!payload) return;
    setLoading(true);
    setError("");
    try {
      const result = await getRecommendation(payload);
      setResponse(result);
      if (!result.ok) setError(result.details || result.error || "Unknown error");
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }

  async function handleApplyPick() {
    const payload = parseStateText();
    if (!payload) return;
    setLoading(true);
    setError("");
    try {
      const result = await applyPick({
        state: payload,
        picked_player_id: pickedPlayerId,
        picked_by_slot: pickedBySlot,
        apply_to_user_roster: applyToUserRoster,
        advance_pick: true,
        include_recommendation: false,
      });
      setResponse(result);
      if (result.ok && result.state) {
        setState(result.state);
        setStateText(JSON.stringify(result.state, null, 2));
      } else {
        setError(result.details || result.error || "Unknown error");
      }
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }

  async function handleAfterPick() {
    const payload = parseStateText();
    if (!payload) return;
    setLoading(true);
    setError("");
    try {
      const result = await recommendationAfterPick({
        state: payload,
        picked_player_id: pickedPlayerId,
        picked_by_slot: pickedBySlot,
        apply_to_user_roster: applyToUserRoster,
        advance_pick: true,
      });
      setResponse(result);
      if (result.ok && result.state) {
        setState(result.state);
        setStateText(JSON.stringify(result.state, null, 2));
      } else {
        setError(result.details || result.error || "Unknown error");
      }
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }

  const ctx = getDraftContext(response);

  return (
    <div className="app">
      <TopBar
        currentPick={ctx?.current_pick ?? state.current_pick}
        nextUserPick={ctx?.next_user_pick}
        teamsUntilNextPick={ctx?.teams_until_next_pick}
      />

      <div className="layout">
        <div className="main-column">
          <RecommendationCard
            recommendation={getPrimaryRecommendation(response)}
            loading={loading}
          />
          <RecommendationLists
            alternates={getAlternates(response)}
            valueFalls={getValueFalls(response)}
            waitOnIt={getWaitOnIt(response)}
          />
        </div>

        <div className="side-column">
          <RosterPanel rosterPlayerIds={state.user_roster_player_ids} />
          <DraftControls
            onRefreshRecommendation={handleRecommendation}
            includeDebug={includeDebug}
            setIncludeDebug={setIncludeDebug}
            topN={topN}
            setTopN={setTopN}
            loading={loading}
          />
          <PickEntry
            pickedPlayerId={pickedPlayerId}
            setPickedPlayerId={setPickedPlayerId}
            pickedBySlot={pickedBySlot}
            setPickedBySlot={setPickedBySlot}
            applyToUserRoster={applyToUserRoster}
            setApplyToUserRoster={setApplyToUserRoster}
            onApplyPick={handleApplyPick}
            onAfterPick={handleAfterPick}
            loading={loading}
          />
        </div>
      </div>

      <DebugDrawer
        open={debugOpen}
        setOpen={setDebugOpen}
        stateText={stateText}
        setStateText={setStateText}
        stateJsonError={stateJsonError}
        response={response}
        error={error}
      />
    </div>
  );
}