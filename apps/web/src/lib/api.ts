import type {
  AiProviderProfileResponse,
  AiProviderResponse,
  CorrectAnswerRequest,
  CreateAiProviderProfileRequest,
  CreateDiagnosticSessionRequest,
  CreateLearningRunRequest,
  CreatePlanningProposalRequest,
  CreateSourceCheckRequest,
  DiagnosticSessionResponse,
  ActivityAttemptSubmissionResponse,
  EmailOutboxProcessResponse,
  NotificationPreferenceResponse,
  NotificationResponse,
  PlanningProposalResponse,
  PlanningOptionResponse,
  LearningEvidenceResponse,
  LearningRunResponse,
  PrivacySettingsResponse,
  ResolveSourceChangeRequest,
  SourceChangeCandidateResponse,
  SourceCheckRunResponse,
  SubmitAnswerRequest,
  SubmitActivityAttemptRequest,
  SelfReviewAttemptRequest,
  SelfReviewAttemptResponse,
  StartReviewResponse,
  TodayLearningRequest,
  TodayLearningResponse,
  UpdateNotificationPreferenceRequest,
  UpdatePlanningStatusRequest,
  UpdatePlanningUnitRequest,
  UpdatePrivacySettingsRequest,
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

export function messageForError(error: unknown): string {
  if (error instanceof ApiError) {
    return error.message;
  }
  if (error instanceof TypeError) {
    return "无法连接本地 API。请确认 FastAPI 已在 127.0.0.1:8000 启动。";
  }
  return "发生未知错误，请稍后重试。";
}
