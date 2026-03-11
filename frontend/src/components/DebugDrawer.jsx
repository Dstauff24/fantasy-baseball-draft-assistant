export default function DebugDrawer({
  open,
  setOpen,
  stateText,
  setStateText,
  stateJsonError,
  response,
  error,
}) {
  return (
    <div className="debug-drawer">
      <button className="debug-toggle" onClick={() => setOpen(!open)}>
        {open ? "Hide Debug" : "Show Debug"}
      </button>

      {open && (
        <div className="debug-body">
          <div className="debug-section">
            <h4>Draft State (editable JSON)</h4>
            {stateJsonError && <p className="error-text">{stateJsonError}</p>}
            <textarea
              rows={12}
              value={stateText}
              onChange={(e) => setStateText(e.target.value)}
            />
          </div>

          <div className="debug-section">
            <h4>Last Response</h4>
            <pre>{response ? JSON.stringify(response, null, 2) : "None"}</pre>
          </div>

          {error && (
            <div className="debug-section">
              <h4>Error</h4>
              <pre className="error-text">{error}</pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}