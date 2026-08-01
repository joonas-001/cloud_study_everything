import type { ExperimentResponse } from "@/generated/api-schema";

export function experimentGateCopy(gate: ExperimentResponse["gate_level"]): {
  title: string;
  description: string;
} {
  const values = {
    draft_only: {
      title: "仅可保存草稿",
      description: "六维证据或复核尚未满足本地实验批准条件。",
    },
    local_ready: {
      title: "可以开展本地实验",
      description: "可以整理作品和计划，但不能记录真实求职动作。",
    },
    action_ready: {
      title: "可以记录手动外部动作",
      description: "门禁已满足；系统仍不会替你投递、联系、登录或交易。",
    },
    blocked: {
      title: "上下文已阻断",
      description: "目标、版本或技能包摘要不一致，需要重新建立有效实验。",
    },
  } satisfies Record<
    ExperimentResponse["gate_level"],
    { title: string; description: string }
  >;
  return values[gate];
}

export function experimentReasonCopy(code: string): string {
  const fixed: Record<string, string> = {
    local_gate_satisfied: "六维证据齐全且没有阻断性复核标记。",
    action_gate_satisfied: "真实动作所需的 Runner、保持、真人评审和市场复核均已满足。",
    goal_not_employment: "当前目标不是首版允许的就业目标。",
    goal_superseded: "实验引用的目标已被更新的目标取代。",
    skill_version_mismatch: "学习记录与实验锁定的技能版本不一致。",
    skill_manifest_mismatch: "锁定技能包摘要发生不一致。",
    operation_verified_required: "操作能力尚未达到对应范围的 verified。",
    retention_retained_required: "保持能力尚未达到对应范围的 retained。",
    independent_transfer_review_required: "迁移能力缺少合格的外部真人评审。",
    independent_artifact_review_required: "作品证据缺少合格的外部真人评审。",
    market_review_missing: "没有关联同一目标和能力范围的市场研究。",
    market_review_not_accepted: "关联市场研究尚未完成并由用户接受。",
    market_research_context_mismatch: "市场研究与当前目标、版本或能力范围不一致。",
    path_not_enabled: "首版没有启用这条路径。",
  };
  if (code.startsWith("evidence_dimension_missing:")) {
    return `缺少六维证据：${code.split(":")[1]}`;
  }
  if (code.startsWith("review_flag_blocking:")) {
    return `存在阻断复核：${code.split(":").slice(1).join(" / ")}`;
  }
  return fixed[code] ?? code;
}

export function availableExperimentActions(
  status: ExperimentResponse["status"],
): Array<ExperimentResponse["status"] | "approve" | "start" | "resume" | "reject"> {
  const actions: Record<string, Array<string>> = {
    draft: ["approve", "reject", "ended"],
    blocked: ["approve", "ended"],
    approved: ["start", "paused", "ended"],
    active: ["paused", "completed", "ended"],
    paused: ["resume", "completed", "ended"],
  };
  return (actions[status] ?? []) as Array<
    ExperimentResponse["status"] | "approve" | "start" | "resume" | "reject"
  >;
}
