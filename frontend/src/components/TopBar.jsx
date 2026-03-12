import { formatPickNumber, formatTeamsUntilPick } from "../utils/formatters";

export default function TopBar({ currentPick, nextUserPick, teamsUntilNextPick }) {
  return (
    <div className="topbar">
      <div className="topbar-item">
        <span className="topbar-label">Current Pick</span>
        <span className="topbar-value">{formatPickNumber(currentPick)}</span>
      </div>
      <div className="topbar-item">
        <span className="topbar-label">Your Next Pick</span>
        <span className="topbar-value">{formatPickNumber(nextUserPick)}</span>
      </div>
      <div className="topbar-item">
        <span className="topbar-label">Urgency</span>
        <span className="topbar-value">{formatTeamsUntilPick(teamsUntilNextPick)}</span>
      </div>
    </div>
  );
}