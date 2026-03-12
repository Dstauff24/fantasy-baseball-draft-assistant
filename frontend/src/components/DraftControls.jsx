export default function DraftControls({
  onRefreshRecommendation,
  includeDebug,
  setIncludeDebug,
  topN,
  setTopN,
  loading,
}) {
  return (
    <div className="card">
      <h3>Draft Controls</h3>
      <div className="row">
        <label>Top N</label>
        <input
          type="number"
          value={topN}
          min={1}
          max={30}
          onChange={(e) => setTopN(Number(e.target.value))}
        />
      </div>
      <div className="row">
        <label>Debug Mode</label>
        <input
          type="checkbox"
          checked={includeDebug}
          onChange={(e) => setIncludeDebug(e.target.checked)}
        />
      </div>
      <button disabled={loading} onClick={onRefreshRecommendation}>
        {loading ? "Loading..." : "Get Recommendation"}
      </button>
    </div>
  );
}