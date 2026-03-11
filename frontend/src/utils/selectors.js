export function getPrimaryRecommendation(response) {
  if (!response?.recommendation) return null;
  return response.recommendation.headline_recommendation || null;
}

export function getAlternates(response) {
  return response?.recommendation?.alternate_recommendations || [];
}

export function getValueFalls(response) {
  return response?.recommendation?.value_falls || [];
}

export function getWaitOnIt(response) {
  return response?.recommendation?.wait_on_it_candidates || [];
}

export function getDraftContext(response) {
  return response?.recommendation?.draft_context || null;
}

export function getStrategicExplanation(response) {
  return response?.recommendation?.strategic_explanation || [];
}

export function getRiskFlags(response) {
  return response?.recommendation?.risk_flags || [];
}