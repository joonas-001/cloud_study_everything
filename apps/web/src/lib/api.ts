import type {
  CorrectAnswerRequest,
  CreateDiagnosticSessionRequest,
  DiagnosticSessionResponse,
  PrivacySettingsResponse,
  SubmitAnswerRequest,
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

export function messageForError(error: unknown): string {
  if (error instanceof ApiError) {
    return error.message;
  }
  if (error instanceof TypeError) {
    return "无法连接本地 API。请确认 FastAPI 已在 127.0.0.1:8000 启动。";
  }
  return "发生未知错误，请稍后重试。";
}
