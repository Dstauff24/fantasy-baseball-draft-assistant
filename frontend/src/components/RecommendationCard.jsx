import { formatPlayerLabel, formatPositions, formatScore, fallback } from "../utils/formatters";

export default function RecommendationCard({ recommendation, loading }) {
  if (loading) return <div className="card">Loading recommendation...</div>;
  if (!recommendation) return <div className="card muted">No recommendation yet. Submit draft state to begin.</div>;

  return (
    <div className="card hero-card">
      <div className="hero-header">
        <h2>{formatPlayerLabel(recommendation)}</h2>
        <span className="badge">{formatPositions(recommendation.positions)}</span>
        {recommendation.team && <span className="badge muted">{recommendation.team}</span>}
      </div>

      <div className="scores-row">
        <div className="score-item">
          <span className="score-label">Draft Score</span>
          <span className="score-value">{formatScore(recommendation.draft_score)}</span>
        </div>
        <div className="score-item">
          <span className="score-label">Survival</span>
          <span className="score-value">{formatScore(recommendation.survival_probability)}</span>
        </div>
        <div className="score-item">
          <span className="score-label">Board Pressure</span>
          <span className="score-value">{formatScore(recommendation.board_pressure_score)}</span>
        </div>
      </div>

      {recommendation.reasoning?.length > 0 && (
        <ul className="reasoning-list">
          {recommendation.reasoning.map((r, i) => <li key={i}>{r}</li>)}
        </ul>
      )}
    </div>
  );
}