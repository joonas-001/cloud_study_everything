import type {
  LearningActivityResponse,
  MasteryDimensionResponse,
  MasteryEvidenceItemResponse,
} from "@/generated/api-schema";

export const EVIDENCE_DIMENSIONS = [
  "understanding",
  "operation",
  "transfer",
  "artifact",
  "retention",
  "correction",
] as const;

export type EvidenceDimensionId = (typeof EVIDENCE_DIMENSIONS)[number];

export const DIMENSION_COPY: Record<
  EvidenceDimensionId,
  { title: string; question: string }
> = {
  understanding: { title: "知识理解", question: "能否解释概念、边界与联系？" },
  operation: { title: "操作能力", question: "能否独立完成代表性任务？" },
  transfer: { title: "迁移能力", question: "能否在陌生情境中应用？" },
  artifact: { title: "作品证据", question: "是否存在可检查的真实成果？" },
  retention: { title: "保持程度", question: "间隔后是否仍能完成任务？" },
  correction: { title: "纠错能力", question: "能否定位原因并完成修正？" },
};

export const EVIDENCE_LEVEL_COPY: Record<
  MasteryDimensionResponse["evidence_level"],
  { label: string; order: number; boundary: string }
> = {
  none: { label: "尚无证据", order: 0, boundary: "当前记录没有该维度证据；不等于能力不存在。" },
  limited: { label: "有限证据", order: 1, boundary: "只能支持本次有限范围，仍需更强或独立验证。" },
  supported: { label: "确定性支持", order: 2, boundary: "受规则支持，但不等于 Runner 验证或保持证据。" },
  verified: { label: "Runner 范围验证", order: 3, boundary: "只证明锁定任务范围，不外推为整门掌握。" },
  retained: { label: "延迟保持证据", order: 4, boundary: "只证明同范围延迟复测，不是无限期结论。" },
};

export const REVIEW_FLAG_COPY: Record<
  MasteryDimensionResponse["review_flags"][number],
  string
> = {
  manual_review_pending: "待独立人工复核",
  retention_due: "待延迟复习",
  source_review_pending: "来源待复核",
  version_mismatch: "精确版本不一致",
};

export const EVIDENCE_STRENGTH_COPY: Record<
  MasteryEvidenceItemResponse["strength"],
  string
> = {
  limited: "有限",
  supported: "支持",
  retained_limited: "有限保持",
  verified: "Runner 范围验证",
  retained: "延迟范围保持",
};

export function evidenceActivityTitle(
  evidence: MasteryEvidenceItemResponse,
  activities: readonly LearningActivityResponse[],
): string {
  return activities.find((activity) => activity.id === evidence.activity_id)?.title ??
    "历史活动（当前响应未包含标题）";
}

export function dimensionEvidence(
  dimension: EvidenceDimensionId,
  evidence: readonly MasteryEvidenceItemResponse[],
): MasteryEvidenceItemResponse[] {
  return evidence
    .filter((item) => item.dimension === dimension && item.superseded_at === null)
    .sort((left, right) => right.created_at.localeCompare(left.created_at));
}

export function evidenceUpdatedAt(dimensions: readonly MasteryDimensionResponse[]): string | null {
  const values = dimensions
    .map((dimension) => dimension.updated_at)
    .filter(Boolean)
    .sort((left, right) => right.localeCompare(left));
  return values[0] ?? null;
}
