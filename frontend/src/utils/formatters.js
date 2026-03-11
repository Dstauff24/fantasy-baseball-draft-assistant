export function formatPickNumber(n) {
  if (n == null) return "--";
  return `Pick #${n}`;
}

export function formatPositions(positions) {
  if (!positions || positions.length === 0) return "N/A";
  return positions.join(", ");
}

export function formatScore(score) {
  if (score == null) return "--";
  return (score * 100).toFixed(1);
}

export function formatPlayerLabel(player) {
  if (!player) return "None";
  return player.player_name || player.player_id || "Unknown";
}

export function formatTeamsUntilPick(n) {
  if (n == null) return "--";
  if (n === 0) return "Your pick now";
  if (n === 1) return "1 team away";
  return `${n} teams away`;
}

export function fallback(value, placeholder = "--") {
  return value != null && value !== "" ? value : placeholder;
}