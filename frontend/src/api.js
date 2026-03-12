const API_BASE = import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000";

async function post(path, body) {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body)
  });
  return res.json();
}

export function getRecommendation(payload) {
  return post("/api/recommendation", payload);
}

export function applyPick(payload) {
  return post("/api/apply-pick", payload);
}

export function recommendationAfterPick(payload) {
  return post("/api/recommendation-after-pick", payload);
}