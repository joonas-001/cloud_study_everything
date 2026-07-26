export interface PlatformMilestone {
  title: string;
  description: string;
}

const milestones: readonly PlatformMilestone[] = [
  {
    title: "可信内容边界",
    description: "技能包、来源与版本记录在进入应用前必须通过确定性校验。",
  },
  {
    title: "可复现工程基线",
    description: "前后端锁定依赖和运行时，并在本地与 CI 运行同一组检查。",
  },
  {
    title: "最小本地服务",
    description: "FastAPI 负责启动门禁与 SQLite 初始化，Next.js 提供学习界面入口。",
  },
];

export function getPlatformMilestones(): readonly PlatformMilestone[] {
  return milestones;
}
