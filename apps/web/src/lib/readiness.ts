import type {
  PathComparisonResponse,
  ReadinessEvaluationResponse,
  SelectUserGoalRequest,
} from "@/generated/api-schema";

export type GoalKind = SelectUserGoalRequest["goal_kind"];

export interface EvidenceDimensionView {
  dimension: string;
  evidence_level: string;
  evidence_count: number;
  review_flags: Array<string>;
  updated_at: string | null;
}

export interface ComparisonPathView {
  path: string;
  selected_goal: boolean;
  evidence_gaps: Array<string>;
  factors: Array<Record<string, unknown>>;
  source_ids: Array<string>;
  uncertainties: Array<string>;
}

export function isMonetizationGoal(goal: GoalKind): boolean {
  return ["employment", "freelancing", "productization"].includes(goal);
}

export function readinessStatusCopy(status: string): {
  title: string;
  description: string;
} {
  const values: Record<string, { title: string; description: string }> = {
    not_applicable: {
      title: "本次不适用变现比较",
      description: "你选择的是非变现目标。系统保留能力证据与缺口，不会强制推荐求职。",
    },
    not_ready: {
      title: "证据仍不足",
      description: "当前只能展示具体缺口，不能形成路径建议。",
    },
    review_required: {
      title: "需要先复核",
      description: "证据标记或合成快照状态阻断了本次比较。",
    },
    comparison_ready: {
      title: "可以进行本地合成比较",
      description: "仅允许使用显著标记的合成夹具，不代表真实市场需求。",
    },
    experiment_ready: {
      title: "实验门禁状态",
      description: "5A 不允许真实用户进入此状态。",
    },
  };
  return (
    values[status] ?? {
      title: "未知状态",
      description: "当前结果无法解释，请保留记录并检查契约。",
    }
  );
}

export function reasonCodeCopy(code: string): string {
  const fixed: Record<string, string> = {
    goal_not_monetization: "当前目标不是就业、接单或产品化。",
    learning_run_missing: "尚未选择带有六维证据的学习记录。",
    comparison_allowed: "确定性规则允许生成本地合成比较。",
    experiment_threshold_unconfirmed: "真实实验最低证据仍未确认。",
    market_snapshot_stale: "所选合成快照用于模拟过期状态。",
    market_snapshot_conflicted: "所选合成快照用于模拟来源冲突。",
    market_snapshot_indeterminate: "所选合成快照用于模拟无法判断。",
  };
  if (code.startsWith("evidence_dimension_missing:")) {
    return `缺少维度证据：${code.split(":")[1]}`;
  }
  if (code.startsWith("review_flag_blocking:")) {
    return `存在阻断复核标记：${code.split(":")[1]}`;
  }
  return fixed[code] ?? code;
}

export function evidenceDimensions(
  evaluation: ReadinessEvaluationResponse | null,
): Array<EvidenceDimensionView> {
  if (!evaluation) return [];
  const snapshot = evaluation.evidence_snapshot as {
    dimensions?: Array<Partial<EvidenceDimensionView>>;
  };
  if (!Array.isArray(snapshot.dimensions)) return [];
  return snapshot.dimensions.map((item) => ({
    dimension: item.dimension ?? "unknown",
    evidence_level: item.evidence_level ?? "none",
    evidence_count:
      typeof item.evidence_count === "number" ? item.evidence_count : 0,
    review_flags: Array.isArray(item.review_flags) ? item.review_flags : [],
    updated_at: typeof item.updated_at === "string" ? item.updated_at : null,
  }));
}

export function comparisonPaths(
  comparison: PathComparisonResponse | null,
): Array<ComparisonPathView> {
  if (!comparison || !Array.isArray(comparison.paths)) return [];
  return comparison.paths.map((item) => {
    const value = item as Partial<ComparisonPathView>;
    return {
      path: value.path ?? "unknown",
      selected_goal: value.selected_goal === true,
      evidence_gaps: Array.isArray(value.evidence_gaps)
        ? value.evidence_gaps
        : [],
      factors: Array.isArray(value.factors) ? value.factors : [],
      source_ids: Array.isArray(value.source_ids) ? value.source_ids : [],
      uncertainties: Array.isArray(value.uncertainties)
        ? value.uncertainties
        : [],
    };
  });
}
