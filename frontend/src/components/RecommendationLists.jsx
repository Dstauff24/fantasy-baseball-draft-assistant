import { formatPlayerLabel, formatPositions, formatScore } from "../utils/formatters";

function PlayerRow({ player }) {
  return (
    <div className="player-row">
      <span className="player-name">{formatPlayerLabel(player)}</span>
      <span className="player-pos">{formatPositions(player.positions)}</span>
      <span className="player-score">{formatScore(player.draft_score)}</span>
    </div>
  );
}

function Section({ title, players }) {
  if (!players || players.length === 0) return null;
  return (
    <div className="list-section">
      <h3>{title}</h3>
      {players.map((p, i) => <PlayerRow key={p.player_id || i} player={p} />)}
    </div>
  );
}

export default function RecommendationLists({ alternates, valueFalls, waitOnIt }) {
  return (
    <div className="card">
      <Section title="Alternates" players={alternates} />
      <Section title="Value Falls" players={valueFalls} />
      <Section title="Wait On It" players={waitOnIt} />
    </div>
  );
}