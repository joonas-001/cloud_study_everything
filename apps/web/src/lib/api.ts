import type {
  AiProviderProfileResponse,
  AiProviderResponse,
  CapabilityScopeResponse,
  CorrectAnswerRequest,
  CreatePathComparisonRequest,
  CreateReadinessEvaluationRequest,
  CreateAiProviderProfileRequest,
  CreateDiagnosticSessionRequest,
  CreateLearningRunRequest,
  CreatePlanningProposalRequest,
  CreateSourceCheckRequest,
  DiagnosticSessionResponse,
  DecidePathComparisonRequest,
  ActivityAttemptSubmissionResponse,
  EmailOutboxProcessResponse,
  NotificationPreferenceResponse,
  NotificationResponse,
  PlanningProposalResponse,
  PlanningOptionResponse,
  LearningEvidenceResponse,
  LearningRunResponse,
  MarketResearchOverviewResponse,
  MarketResearchHistoryResponse,
  MarketResearchRunResponse,
  MarketSnapshotResponse,
  PathComparisonDecisionResponse,
  PathComparisonResponse,
  PrivacySettingsResponse,
  ReadinessEvaluationResponse,
  ReadinessHistoryResponse,
  ResolveSourceChangeRequest,
  RunnerAvailabilityResponse,
  SourceChangeCandidateResponse,
  SourceCheckRunResponse,
  SubmitAnswerRequest,
  SubmitActivityAttemptRequest,
  SelfReviewAttemptRequest,
  SelfReviewAttemptResponse,
  SelectUserGoalRequest,
  CreateMarketResearchRunRequest,
  RecoverPreDispatchMarketResearchRequest,
  SynthesizeMarketResearchRequest,
  ReviewMarketResearchRequest,
  ReconcileMarketResearchRequest,
  RedactMarketSourceRequest,
  StartReviewResponse,
  ExecuteRunnerAttemptResponse,
  CreateExperimentRequest,
  ExperimentResponse,
  ExperimentReviewRequest,
  ExperimentTransitionRequest,
  ExperimentActionRequest,
  ExperimentOutcomeRequest,
  CreateIncomeRequest,
  ReviseIncomeRequest,
  RedactIncomeRequest,
  CreateFeedbackRequest,
  DecideFeedbackRequest,
  ExportExperimentRequest,
  TodayLearningRequest,
  TodayLearningResponse,
  UpdateNotificationPreferenceRequest,
  UpdatePlanningStatusRequest,
  UpdatePlanningUnitRequest,
  UpdatePrivacySettingsRequest,
  UserGoalResponse,
} from "@/generated/api-schema";

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/$/, "") ??
  "http://127.0.0.1:8000";

interface ApiErrorBody {
  detail?: {
    code?: string;
    message?: string;
  };
}

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...init?.headers,
    },
  });
  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as ApiErrorBody;
    throw new ApiError(
      response.status,
      body.detail?.code ?? "request_failed",
      body.detail?.message ?? `请求失败（HTTP ${response.status}）`,
    );
  }
  return (await response.json()) as T;
}

export function getPrivacySettings(): Promise<PrivacySettingsResponse> {
  return request("/settings/privacy");
}

export function updatePrivacySettings(
  payload: UpdatePrivacySettingsRequest,
): Promise<PrivacySettingsResponse> {
  return request("/settings/privacy", {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export function getActiveDiagnosticSession(
  skillId: string,
  skillVersion: string,
): Promise<DiagnosticSessionResponse | null> {
  const query = new URLSearchParams({
    skill_id: skillId,
    skill_version: skillVersion,
  });
  return request<DiagnosticSessionResponse>(
    `/diagnostic-sessions/active?${query.toString()}`,
  ).catch((error: unknown) => {
    if (error instanceof ApiError && error.status === 404) {
      return null;
    }
    throw error;
  });
}

export function createDiagnosticSession(
  payload: CreateDiagnosticSessionRequest,
): Promise<DiagnosticSessionResponse> {
  return request("/diagnostic-sessions", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function submitDiagnosticAnswer(
  sessionId: string,
  payload: SubmitAnswerRequest,
): Promise<DiagnosticSessionResponse> {
  return request(`/diagnostic-sessions/${sessionId}/answers`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function correctDiagnosticAnswer(
  sessionId: string,
  questionId: string,
  payload: CorrectAnswerRequest,
): Promise<DiagnosticSessionResponse> {
  return request(
    `/diagnostic-sessions/${sessionId}/answers/${questionId}/corrections`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
}

export function endDiagnosticSession(
  sessionId: string,
): Promise<DiagnosticSessionResponse> {
  return request(`/diagnostic-sessions/${sessionId}/end`, {
    method: "POST",
  });
}

export function getLatestDiagnosticSession(
  skillId: string,
  skillVersion: string,
): Promise<DiagnosticSessionResponse | null> {
  const query = new URLSearchParams({
    skill_id: skillId,
    skill_version: skillVersion,
  });
  return request<DiagnosticSessionResponse>(
    `/diagnostic-sessions/latest?${query.toString()}`,
  ).catch((error: unknown) => {
    if (error instanceof ApiError && error.status === 404) {
      return null;
    }
    throw error;
  });
}

export function createPlanningProposal(
  payload: CreatePlanningProposalRequest,
): Promise<PlanningProposalResponse> {
  return request("/planning-proposals", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function getLatestPlanningProposal(
  skillId: string,
  skillVersion: string,
): Promise<PlanningProposalResponse | null> {
  const query = new URLSearchParams({
    skill_id: skillId,
    skill_version: skillVersion,
  });
  return request<PlanningProposalResponse>(
    `/planning-proposals/latest?${query.toString()}`,
  ).catch((error: unknown) => {
    if (error instanceof ApiError && error.status === 404) {
      return null;
    }
    throw error;
  });
}

export function updatePlanningUnit(
  proposalId: string,
  unitId: string,
  payload: UpdatePlanningUnitRequest,
): Promise<PlanningProposalResponse> {
  return request(`/planning-proposals/${proposalId}/units/${unitId}`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export function updatePlanningStatus(
  proposalId: string,
  payload: UpdatePlanningStatusRequest,
): Promise<PlanningProposalResponse> {
  return request(`/planning-proposals/${proposalId}/status`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function getLearningPlanOptions(
  skillId: string,
  skillVersion: string,
): Promise<Array<PlanningOptionResponse>> {
  const query = new URLSearchParams({
    skill_id: skillId,
    skill_version: skillVersion,
  });
  return request(`/learning-plan-options?${query.toString()}`);
}

export function createLearningRun(
  payload: CreateLearningRunRequest,
): Promise<LearningRunResponse> {
  return request("/learning-runs", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function getActiveLearningRun(
  skillId: string,
  skillVersion: string,
): Promise<LearningRunResponse | null> {
  const query = new URLSearchParams({
    skill_id: skillId,
    skill_version: skillVersion,
  });
  return request<LearningRunResponse>(
    `/learning-runs/active?${query.toString()}`,
  ).catch((error: unknown) => {
    if (error instanceof ApiError && error.status === 404) {
      return null;
    }
    throw error;
  });
}

export function getLatestLearningRun(
  skillId: string,
  skillVersion: string,
): Promise<LearningRunResponse | null> {
  const query = new URLSearchParams({
    skill_id: skillId,
    skill_version: skillVersion,
  });
  return request<LearningRunResponse>(
    `/learning-run-latest?${query.toString()}`,
  ).catch((error: unknown) => {
    if (error instanceof ApiError && error.status === 404) {
      return null;
    }
    throw error;
  });
}

export function getLearningRun(runId: string): Promise<LearningRunResponse> {
  return request(`/learning-runs/${runId}`);
}

export function generateTodayLearning(
  runId: string,
  payload: TodayLearningRequest,
): Promise<TodayLearningResponse> {
  return request(`/learning-runs/${runId}/today`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function submitLearningActivityAttempt(
  activityId: string,
  payload: SubmitActivityAttemptRequest,
): Promise<ActivityAttemptSubmissionResponse> {
  return request(`/learning-activities/${activityId}/attempts`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function correctLearningActivityAttempt(
  activityId: string,
  attemptId: string,
  payload: SubmitActivityAttemptRequest,
): Promise<ActivityAttemptSubmissionResponse> {
  return request(
    `/learning-activities/${activityId}/attempts/${attemptId}/corrections`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
}

export function selfReviewActivityAttempt(
  attemptId: string,
  payload: SelfReviewAttemptRequest,
): Promise<SelfReviewAttemptResponse> {
  return request(`/activity-attempts/${attemptId}/self-review`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function getRunnerAvailability(): Promise<RunnerAvailabilityResponse> {
  return request("/runner/availability");
}

export function executeRunnerAttempt(
  attemptId: string,
): Promise<ExecuteRunnerAttemptResponse> {
  return request(`/activity-attempts/${attemptId}/execute`, {
    method: "POST",
  });
}

export function getLearningEvidence(
  runId: string,
): Promise<LearningEvidenceResponse> {
  return request(`/learning-runs/${runId}/evidence`);
}

export function startLearningReview(
  reviewId: string,
): Promise<StartReviewResponse> {
  return request(`/review-tasks/${reviewId}/start`, { method: "POST" });
}

export function endLearningRun(runId: string): Promise<LearningRunResponse> {
  return request(`/learning-runs/${runId}/end`, { method: "POST" });
}

export function getReadinessScopes(): Promise<Array<CapabilityScopeResponse>> {
  return request("/readiness/scopes");
}

export function selectReadinessGoal(
  payload: SelectUserGoalRequest,
): Promise<UserGoalResponse> {
  return request("/readiness/goals", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function getCurrentReadinessGoal(
  skillId: string,
  skillVersion: string,
  capabilityScopeId: string,
): Promise<UserGoalResponse | null> {
  const query = new URLSearchParams({
    skill_id: skillId,
    skill_version: skillVersion,
    capability_scope_id: capabilityScopeId,
  });
  return request(`/readiness/goals/current?${query.toString()}`);
}

export function getSyntheticMarketSnapshots(): Promise<
  Array<MarketSnapshotResponse>
> {
  return request("/readiness/market-snapshots");
}

export function createReadinessEvaluation(
  payload: CreateReadinessEvaluationRequest,
): Promise<ReadinessEvaluationResponse> {
  return request("/readiness/evaluations", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function createPathComparison(
  payload: CreatePathComparisonRequest,
): Promise<PathComparisonResponse> {
  return request("/readiness/comparisons", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function decidePathComparison(
  comparisonId: string,
  payload: DecidePathComparisonRequest,
): Promise<PathComparisonDecisionResponse> {
  return request(`/readiness/comparisons/${comparisonId}/decisions`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function getReadinessHistory(
  goalSelectionId: string,
): Promise<ReadinessHistoryResponse> {
  return request(`/readiness/goals/${goalSelectionId}/history`);
}

export function listExperiments(
  goalSelectionId?: string,
): Promise<Array<ExperimentResponse>> {
  const query = new URLSearchParams();
  if (goalSelectionId) query.set("goal_selection_id", goalSelectionId);
  const suffix = query.size ? `?${query.toString()}` : "";
  return request(`/experiments${suffix}`);
}

export function createExperiment(
  payload: CreateExperimentRequest,
): Promise<ExperimentResponse> {
  return request("/experiments", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function getExperiment(
  experimentId: string,
  revealIncome = false,
): Promise<ExperimentResponse> {
  const query = new URLSearchParams({ reveal_income: String(revealIncome) });
  return request(
    `/experiments/${encodeURIComponent(experimentId)}?${query.toString()}`,
  );
}

export function addExperimentReview(
  experimentId: string,
  payload: ExperimentReviewRequest,
): Promise<ExperimentResponse> {
  return request(`/experiments/${encodeURIComponent(experimentId)}/reviews`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function reevaluateExperimentGate(
  experimentId: string,
): Promise<ExperimentResponse> {
  return request(
    `/experiments/${encodeURIComponent(experimentId)}/gate-evaluations`,
    { method: "POST" },
  );
}

export function transitionExperiment(
  experimentId: string,
  payload: ExperimentTransitionRequest,
): Promise<ExperimentResponse> {
  return request(
    `/experiments/${encodeURIComponent(experimentId)}/transitions`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
}

export function recordExperimentAction(
  experimentId: string,
  payload: ExperimentActionRequest,
): Promise<ExperimentResponse> {
  return request(`/experiments/${encodeURIComponent(experimentId)}/actions`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function recordExperimentOutcome(
  experimentId: string,
  payload: ExperimentOutcomeRequest,
): Promise<ExperimentResponse> {
  return request(`/experiments/${encodeURIComponent(experimentId)}/outcomes`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function createExperimentIncome(
  experimentId: string,
  payload: CreateIncomeRequest,
): Promise<ExperimentResponse> {
  return request(`/experiments/${encodeURIComponent(experimentId)}/income`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function reviseExperimentIncome(
  experimentId: string,
  incomeRecordId: string,
  payload: ReviseIncomeRequest,
): Promise<ExperimentResponse> {
  return request(
    `/experiments/${encodeURIComponent(experimentId)}/income/${encodeURIComponent(incomeRecordId)}/revisions`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
}

export function redactExperimentIncome(
  experimentId: string,
  incomeRecordId: string,
  payload: RedactIncomeRequest,
): Promise<ExperimentResponse> {
  return request(
    `/experiments/${encodeURIComponent(experimentId)}/income/${encodeURIComponent(incomeRecordId)}/redact`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
}

export function createExperimentFeedback(
  experimentId: string,
  payload: CreateFeedbackRequest,
): Promise<ExperimentResponse> {
  return request(`/experiments/${encodeURIComponent(experimentId)}/feedback`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function decideExperimentFeedback(
  experimentId: string,
  feedbackId: string,
  payload: DecideFeedbackRequest,
): Promise<ExperimentResponse> {
  return request(
    `/experiments/${encodeURIComponent(experimentId)}/feedback/${encodeURIComponent(feedbackId)}/decisions`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
}

export async function exportExperiment(
  experimentId: string,
  payload: ExportExperimentRequest,
): Promise<Blob> {
  const response = await fetch(
    `${API_BASE_URL}/experiments/${encodeURIComponent(experimentId)}/exports`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  );
  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as ApiErrorBody;
    throw new ApiError(
      response.status,
      body.detail?.code ?? "request_failed",
      body.detail?.message ?? `请求失败（HTTP ${response.status}）`,
    );
  }
  return response.blob();
}

export function createSourceCheck(
  payload: CreateSourceCheckRequest,
): Promise<SourceCheckRunResponse> {
  return request("/source-check-runs", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function getSourceChangeCandidates(
  skillId: string,
  skillVersion: string,
): Promise<Array<SourceChangeCandidateResponse>> {
  const query = new URLSearchParams({
    skill_id: skillId,
    skill_version: skillVersion,
  });
  return request(`/source-change-candidates?${query.toString()}`);
}

export function resolveSourceChangeCandidate(
  candidateId: string,
  payload: ResolveSourceChangeRequest,
): Promise<SourceChangeCandidateResponse> {
  return request(`/source-change-candidates/${candidateId}/decision`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function getNotifications(): Promise<Array<NotificationResponse>> {
  return request("/notifications");
}

export function markNotificationRead(
  notificationId: string,
): Promise<NotificationResponse> {
  return request(`/notifications/${notificationId}/read`, { method: "POST" });
}

export function processEmailOutbox(): Promise<EmailOutboxProcessResponse> {
  return request("/notifications/email-outbox/process", { method: "POST" });
}

export function getNotificationPreferences(): Promise<NotificationPreferenceResponse> {
  return request("/settings/notifications");
}

export function updateNotificationPreferences(
  payload: UpdateNotificationPreferenceRequest,
): Promise<NotificationPreferenceResponse> {
  return request("/settings/notifications", {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export function sendTestEmail(): Promise<NotificationResponse> {
  return request("/settings/notifications/test-email", { method: "POST" });
}

export function getAiProviders(): Promise<Array<AiProviderResponse>> {
  return request("/ai/providers");
}

export function getAiProviderProfiles(): Promise<
  Array<AiProviderProfileResponse>
> {
  return request("/ai/provider-profiles");
}

export function createAiProviderProfile(
  payload: CreateAiProviderProfileRequest,
): Promise<AiProviderProfileResponse> {
  return request("/ai/provider-profiles", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function getMarketResearchOverview(
  goalSelectionId?: string,
): Promise<MarketResearchOverviewResponse> {
  const query = new URLSearchParams();
  if (goalSelectionId) {
    query.set("goal_selection_id", goalSelectionId);
  }
  const suffix = query.size ? `?${query.toString()}` : "";
  return request(`/market-research/overview${suffix}`);
}

export function getMarketResearchHistory(
  limit = 20,
): Promise<MarketResearchHistoryResponse> {
  const query = new URLSearchParams({ limit: String(limit) });
  return request(`/market-research/history?${query.toString()}`);
}

export function createMarketResearchRun(
  payload: CreateMarketResearchRunRequest,
): Promise<MarketResearchRunResponse> {
  return request("/market-research/runs", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function synthesizeMarketResearch(
  runId: string,
  payload: SynthesizeMarketResearchRequest,
): Promise<MarketResearchRunResponse> {
  return request(`/market-research/runs/${runId}/synthesis`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function recoverPreDispatchMarketResearch(
  runId: string,
  payload: RecoverPreDispatchMarketResearchRequest,
): Promise<MarketResearchRunResponse> {
  return request(`/market-research/runs/${runId}/recover-pre-dispatch`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function completeMarketResearchMetadataOnly(
  runId: string,
): Promise<MarketResearchRunResponse> {
  return request(`/market-research/runs/${runId}/complete-metadata-only`, {
    method: "POST",
  });
}

export function reviewMarketResearch(
  runId: string,
  payload: ReviewMarketResearchRequest,
): Promise<MarketResearchRunResponse> {
  return request(`/market-research/runs/${runId}/review`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function reconcileMarketResearchRecovery(
  runId: string,
  payload: ReconcileMarketResearchRequest,
): Promise<MarketResearchRunResponse> {
  return request(`/market-research/runs/${runId}/reconcile-recovery`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function redactMarketResearchSource(
  runId: string,
  sourceId: string,
  payload: RedactMarketSourceRequest,
): Promise<MarketResearchRunResponse> {
  return request(
    `/market-research/runs/${encodeURIComponent(runId)}/sources/${encodeURIComponent(sourceId)}/redact`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
}

export function messageForError(error: unknown): string {
  if (error instanceof ApiError) {
    return error.message;
  }
  if (error instanceof TypeError) {
    return "无法连接本地 API。请确认 FastAPI 已在 127.0.0.1:8000 启动。";
  }
  return "发生未知错误，请稍后重试。";
}
