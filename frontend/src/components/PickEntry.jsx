export default function PickEntry({
  pickedPlayerId,
  setPickedPlayerId,
  pickedBySlot,
  setPickedBySlot,
  applyToUserRoster,
  setApplyToUserRoster,
  onApplyPick,
  onAfterPick,
  loading,
}) {
  return (
    <div className="card">
      <h3>Apply Pick</h3>
      <div className="row">
        <label>Player ID</label>
        <input
          value={pickedPlayerId}
          onChange={(e) => setPickedPlayerId(e.target.value)}
          placeholder="e.g. julio-rodriguez__of"
        />
      </div>
      <div className="row">
        <label>Picked By Slot</label>
        <input
          type="number"
          value={pickedBySlot}
          onChange={(e) => setPickedBySlot(Number(e.target.value))}
        />
      </div>
      <div className="row">
        <label>Add To My Roster</label>
        <input
          type="checkbox"
          checked={applyToUserRoster}
          onChange={(e) => setApplyToUserRoster(e.target.checked)}
        />
      </div>
      <div className="row">
        <button disabled={loading} onClick={onApplyPick}>
          Apply Pick
        </button>
        <button disabled={loading} onClick={onAfterPick}>
          Apply + Recommend
        </button>
      </div>
    </div>
  );
}