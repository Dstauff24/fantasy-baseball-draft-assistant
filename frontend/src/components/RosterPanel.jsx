export default function RosterPanel({ rosterPlayerIds }) {
  return (
    <div className="card">
      <h3>My Roster</h3>
      {!rosterPlayerIds || rosterPlayerIds.length === 0 ? (
        <p className="muted">No players drafted yet.</p>
      ) : (
        <ul className="roster-list">
          {rosterPlayerIds.map((id, i) => (
            <li key={i}>{id}</li>
          ))}
        </ul>
      )}
    </div>
  );
}