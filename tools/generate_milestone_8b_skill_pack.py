"""Generate the deterministic algorithm@0.3.0 learning-core draft."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = ROOT / "docs" / "architecture" / "milestone-8a-spec.json"
DIAGNOSTIC_CONTENT_PATH = (
    ROOT / "docs" / "architecture" / "milestone-8b-diagnostic-content.json"
)
DIAGNOSTIC_FOLLOWUPS_PATH = (
    ROOT / "docs" / "architecture" / "milestone-8b-diagnostic-followups.json"
)
PACKAGE_ROOT = ROOT / "skill-packs" / "algorithm" / "versions" / "0.3.0"
VERSION = "0.3.0"
TODAY = "2026-08-29"


class IndentedSafeDumper(yaml.SafeDumper):
    """Keep sequence indentation consistent with the hand-maintained registry."""

    def increase_indent(self, flow: bool = False, indentless: bool = False) -> None:
        return super().increase_indent(flow, False)


def write_yaml(relative_path: str, value: dict[str, Any]) -> Path:
    path = PACKAGE_ROOT / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(value, allow_unicode=True, sort_keys=False, width=100),
        encoding="utf-8",
        newline="\n",
    )
    return path


def write_text(relative_path: str, value: str) -> Path:
    path = PACKAGE_ROOT / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8", newline="\n")
    return path


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_catalog() -> dict[str, Any]:
    pending_note = (
        "8B 仅按仓库已有记录固定引用元数据；未进行远程实质内容复核，入口保持关闭，"
        "后续复核前不得据此声称内容已获来源背书。"
    )
    return {
        "schema_version": "1.0.0",
        "skill_id": "algorithm",
        "skill_version": VERSION,
        "sources": [
            {
                "id": "python-tutorial-314",
                "title": "The Python Tutorial",
                "publisher": "Python Software Foundation",
                "url": "https://docs.python.org/3.14/tutorial/",
                "source_type": "official_documentation",
                "authority_tier": 1,
                "authority_rationale": "Python 3.14 官方教程，是语言与内置容器语义的一手说明。",
                "published_version": "3.14",
                "retrieved_at": "2026-07-28",
                "check_mode": "http_metadata",
                "access_note": pending_note,
            },
            {
                "id": "wg21-public-materials",
                "title": "WG21 public papers and working drafts",
                "publisher": "ISO/IEC JTC1/SC22/WG21",
                "url": "https://www.open-std.org/jtc1/sc22/wg21/",
                "source_type": "standard",
                "authority_tier": 1,
                "authority_rationale": "C++ 标准委员会公开材料入口；具体规范结论仍需绑定精确文档。",
                "retrieved_at": TODAY,
                "check_mode": "manual",
                "access_note": pending_note,
            },
            {
                "id": "cpp-reference-containers",
                "title": "Containers library",
                "publisher": "cppreference.com",
                "url": "https://en.cppreference.com/w/cpp/container.html",
                "source_type": "community_reference",
                "authority_tier": 2,
                "authority_rationale": "社区维护的 C++ 标准库参考；关键规范结论必须与 WG21 材料交叉核对。",
                "retrieved_at": "2026-07-28",
                "check_mode": "http_metadata",
                "access_note": pending_note,
            },
            {
                "id": "mit-ocw-6006-2020",
                "title": "Introduction to Algorithms",
                "publisher": "MIT OpenCourseWare",
                "url": "https://ocw.mit.edu/courses/6-006-introduction-to-algorithms-fall-2020/",
                "source_type": "university_course",
                "authority_tier": 2,
                "authority_rationale": "MIT 发布的算法与数据结构课程材料。",
                "published_at": "2020-09-01",
                "retrieved_at": "2026-07-28",
                "check_mode": "http_metadata",
                "access_note": pending_note,
            },
            {
                "id": "mit-mathematics-for-cs",
                "title": "Mathematics for Computer Science",
                "publisher": "MIT OpenCourseWare",
                "url": "https://ocw.mit.edu/courses/6-042j-mathematics-for-computer-science-spring-2015/",
                "source_type": "university_course",
                "authority_tier": 2,
                "authority_rationale": "MIT 发布的计算机科学数学课程材料。",
                "published_at": "2015-02-01",
                "retrieved_at": TODAY,
                "check_mode": "manual",
                "access_note": pending_note,
            },
            {
                "id": "open-data-structures-01g",
                "title": "Open Data Structures",
                "publisher": "Pat Morin",
                "url": "https://opendatastructures.org/",
                "source_type": "textbook",
                "authority_tier": 3,
                "authority_rationale": "公开维护且提供版本与许可说明的数据结构教材。",
                "published_version": "0.1G",
                "retrieved_at": "2026-07-28",
                "check_mode": "http_metadata",
                "access_note": pending_note,
            },
            {
                "id": "erickson-algorithms",
                "title": "Algorithms",
                "publisher": "Jeff Erickson",
                "url": "https://jeffe.cs.illinois.edu/teaching/algorithms/",
                "source_type": "textbook",
                "authority_tier": 3,
                "authority_rationale": "大学算法课程的开放教材，覆盖证明、图、贪心与动态规划。",
                "retrieved_at": TODAY,
                "check_mode": "manual",
                "access_note": pending_note,
            },
            {
                "id": "nist-dads",
                "title": "Dictionary of Algorithms and Data Structures",
                "publisher": "National Institute of Standards and Technology",
                "url": "https://xlinux.nist.gov/dads/",
                "source_type": "government_guidance",
                "authority_tier": 1,
                "authority_rationale": "NIST 维护的算法与数据结构术语词典，用于术语交叉核对。",
                "retrieved_at": TODAY,
                "check_mode": "manual",
                "access_note": pending_note,
            },
            {
                "id": "ies-study-guide",
                "title": "Organizing Instruction and Study to Improve Student Learning",
                "publisher": "U.S. Institute of Education Sciences",
                "url": "https://ies.ed.gov/ncee/wwc/PracticeGuide/1",
                "source_type": "government_guidance",
                "authority_tier": 1,
                "authority_rationale": "教育科学研究院发布并标注证据等级的学习实践指南。",
                "published_at": "2007-09-01",
                "retrieved_at": "2026-07-28",
                "check_mode": "http_metadata",
                "access_note": pending_note,
            },
            {
                "id": "spacing-research-set",
                "title": "Curated spacing-effect research set",
                "publisher": "云奕学本地研究记录",
                "url": "https://local.cloud-study/docs/research/review-policy",
                "source_type": "peer_reviewed_research",
                "authority_tier": 2,
                "authority_rationale": "本地记录的同行评审间隔效应研究集合；仅支持透明固定策略及限制。",
                "retrieved_at": "2026-07-28",
                "check_mode": "manual",
                "access_note": "集合仅索引既有研究记录，不代表产生了新研究结论。",
            },
        ],
        "experts": [
            {
                "id": "mit-algorithms-faculty",
                "name": "MIT 6.006 课程教师团队",
                "expertise_evidence": "由 MIT OpenCourseWare 发布算法与数据结构课程材料。",
                "source_ids": ["mit-ocw-6006-2020"],
                "planning_principles": [
                    "把数据结构、算法分析和问题求解放入同一序列。",
                    "用可观察练习连接抽象概念与工程取舍。",
                ],
            },
            {
                "id": "curriculum-source-panel",
                "name": "8A 来源组合（非真人评审）",
                "expertise_evidence": "由标准、官方文档、大学课程和开放教材组成的可追溯来源组合。",
                "source_ids": [
                    "wg21-public-materials",
                    "python-tutorial-314",
                    "mit-mathematics-for-cs",
                    "erickson-algorithms",
                ],
                "planning_principles": [
                    "关键结论至少映射两个来源，其中至少一个为权威等级一或二。",
                    "来源映射不代替内容正确性抽审或独立真人评审。",
                ],
            },
        ],
    }


def activity_for_role(
    role: str,
    domain: dict[str, Any],
    unit_id: str,
    capability_ids: list[str],
    source_ids: list[str],
) -> dict[str, Any]:
    domain_id = domain["id"]
    activity_id = f"{domain_id}-{role.replace('_', '-')}"
    base = {
        "id": activity_id,
        "unit_id": unit_id,
        "title": f"{domain['title']}：{role}",
        "reason": "形成可追溯的共同主干活动；结果只适用于声明的能力范围。",
        "estimated_minutes": 20,
        "required": True,
        "source_ids": source_ids,
        "capability_ids": capability_ids,
        "activity_roles": [role],
        "language": "none",
        "evidence_ceiling": "limited",
    }
    text_field = {
        "id": "response",
        "kind": "text",
        "label": "作答",
        "required": True,
        "min_length": 20,
        "max_length": 4000,
    }
    if role == "study":
        base.update(
            type="study",
            prompt=f"阅读映射来源并整理{domain['title']}的核心概念、前提和边界。",
            completion_rule="confirmation",
            submission_fields=[
                {
                    "id": "confirmed",
                    "kind": "confirmation",
                    "label": "确认已完成阅读和笔记",
                    "required": True,
                    "min_length": 0,
                    "max_length": 10,
                }
            ],
            evidence_ceiling="none",
        )
    elif role in {"structured_check", "correction"}:
        expected = "checked" if role == "structured_check" else "corrected"
        base.update(
            type="structured_check" if role == "structured_check" else "correction",
            prompt=(
                f"选择 {expected}，并按受管步骤核对{domain['title']}的前提、边界和反例。"
            ),
            completion_rule="deterministic_pass",
            submission_fields=[
                {
                    "id": "result",
                    "kind": "choice",
                    "label": "结构检查结果",
                    "required": True,
                    "min_length": 1,
                    "max_length": 20,
                    "options": [expected, "uncertain"],
                }
            ],
            deterministic_check={
                "field_id": "result",
                "accepted_values": [expected],
                "feedback": "只有受管选项通过；这不证明自由文本技术内容正确。",
            },
            evidence_ceiling="supported",
        )
    elif role in {"runner_cpp", "runner_python"}:
        language = "cpp" if role == "runner_cpp" else "python"
        runtime_name = "C++17" if language == "cpp" else "Python 3.14"
        base.update(
            type="code_text",
            prompt=f"使用 {runtime_name} 读取一个整数并原样输出，验证锁定 Runner 通路。",
            completion_rule="runner_pass",
            submission_fields=[
                {
                    "id": "source",
                    "kind": "code",
                    "label": "源代码",
                    "required": True,
                    "min_length": 10,
                    "max_length": 20000,
                }
            ],
            runner_task_id=f"{activity_id}-task",
            language=language,
            evidence_ceiling="verified",
            estimated_minutes=25,
        )
    elif role == "project":
        base.update(
            type="project_evidence",
            prompt=f"提交一个整合{domain['title']}建模、实现选择、测试和限制的小型作品说明。",
            completion_rule="valid_submission",
            submission_fields=[text_field],
        )
    elif role == "review":
        base.update(
            type="review",
            prompt=f"在固定延迟点重新完成{domain['title']}的提取、代表任务和错误复盘。",
            completion_rule="valid_submission",
            submission_fields=[text_field],
            evidence_ceiling="retained_limited",
        )
    elif role == "transfer":
        base.update(
            type="transfer",
            prompt=f"把{domain['title']}用于一个改变了输入规模或约束的新场景，并说明选择变化。",
            completion_rule="valid_submission",
            submission_fields=[text_field],
        )
    else:
        base.update(
            type="explanation",
            prompt=(
                f"不查看笔记，解释{domain['title']}的关键前提、推理步骤、复杂度条件和反例。"
                if role == "active_recall"
                else f"为{domain['title']}给出逐步证明或最小反例，并明确使用的假设。"
            ),
            completion_rule="valid_submission",
            submission_fields=[text_field],
        )
    return base


def build() -> None:
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    diagnostic_content = json.loads(DIAGNOSTIC_CONTENT_PATH.read_text(encoding="utf-8"))
    diagnostic_followups = json.loads(
        DIAGNOSTIC_FOLLOWUPS_PATH.read_text(encoding="utf-8")
    )
    domains = spec["domains"]
    capabilities = spec["capabilities"]
    units = spec["units"]
    source_matrix = {
        item["domain_id"]: item["source_ids"] for item in spec["source_matrix"]
    }
    coverage_matrix = {item["domain_id"]: item for item in spec["coverage"]}
    capabilities_by_domain = {
        domain["id"]: [
            item for item in capabilities if item["domain_id"] == domain["id"]
        ]
        for domain in domains
    }
    units_by_domain = {
        domain["id"]: [item for item in units if item["domain_id"] == domain["id"]]
        for domain in domains
    }
    capability_ids = {item["id"] for item in capabilities}
    if set(diagnostic_content) != capability_ids:
        raise ValueError(
            "primary diagnostic content must cover every capability exactly"
        )
    if set(diagnostic_followups) != {item["id"] for item in capabilities[:18]}:
        raise ValueError(
            "follow-up diagnostic content must cover the fixed 18-capability sample"
        )
    runner_scenarios = {
        "p": (
            "p-control-flow",
            "读入非负 n，输出 1 到 n 的和",
            [("zero", "0\n", "0\n"), ("one", "1\n", "1\n"), ("five", "5\n", "15\n")],
        ),
        "a": (
            "a-asymptotic",
            "令 i=1，每轮加倍直到 i>=n，输出轮数",
            [("unit", "1\n", "0\n"), ("two", "2\n", "1\n"), ("eight", "8\n", "3\n")],
        ),
        "l": (
            "l-array-sequence",
            "逆序输出输入序列，空序列输出空行",
            [
                ("empty", "0\n", "\n"),
                ("one", "1\n7\n", "7\n"),
                ("many", "4\n1 2 3 4\n", "4 3 2 1\n"),
            ],
        ),
        "h": (
            "h-map-set",
            "输出输入整数序列中不同值的数量",
            [
                ("empty", "0\n", "0\n"),
                ("repeat", "5\n1 1 2 2 2\n", "2\n"),
                ("mixed", "4\n-1 0 1 -1\n", "3\n"),
            ],
        ),
        "s": (
            "s-linear-binary-search",
            "在升序数组中输出目标首次出现的零基下标，不存在输出 -1",
            [
                ("missing", "3 4\n1 3 5\n", "-1\n"),
                ("first", "4 1\n1 1 2 3\n", "0\n"),
                ("last", "3 5\n1 3 5\n", "2\n"),
            ],
        ),
        "r": (
            "r-recursion-state",
            "输出 0 到 10 范围内 n 的阶乘；输出测试不证明递归实现",
            [("base", "0\n", "1\n"), ("one", "1\n", "1\n"), ("five", "5\n", "120\n")],
        ),
        "t": (
            "t-heap-priority",
            "使用优先队列语义输出非空整数序列的最小值",
            [
                ("one", "1\n7\n", "7\n"),
                ("mixed", "4\n3 -1 8 2\n", "-1\n"),
                ("repeat", "3\n5 5 5\n", "5\n"),
            ],
        ),
        "g": (
            "g-bfs-dfs",
            "输出无向图中指定起点到终点是否可达（1 或 0）",
            [
                ("same", "1 0 0 0\n", "1\n"),
                ("reachable", "3 2 0 2\n0 1\n1 2\n", "1\n"),
                ("blocked", "4 2 0 3\n0 1\n2 3\n", "0\n"),
            ],
        ),
        "y": (
            "y-greedy-choice",
            "输出半开区间中可选择的最大互不重叠区间数",
            [
                ("empty", "0\n", "0\n"),
                ("chain", "3\n0 1\n1 2\n2 3\n", "3\n"),
                ("overlap", "3\n0 3\n1 2\n2 4\n", "2\n"),
            ],
        ),
        "d": (
            "d-state-transition",
            "输出 F(0)=0、F(1)=1 的第 n 个 Fibonacci 数",
            [("zero", "0\n", "0\n"), ("one", "1\n", "1\n"), ("ten", "10\n", "55\n")],
        ),
        "q": (
            "q-testing-debugging",
            "输出非空整数序列的最小值和最大值",
            [
                ("one", "1\n4\n", "4 4\n"),
                ("mixed", "4\n3 -1 8 2\n", "-1 8\n"),
                ("negative", "3\n-5 -2 -9\n", "-9 -2\n"),
            ],
        ),
    }

    generated: list[tuple[str, str]] = []
    generated.append(
        (
            "curriculum",
            str(
                write_text(
                    "curriculum/README.md",
                    "# algorithm@0.3.0 共同主干草稿\n\n"
                    "本目录实现里程碑 8B 的静态内容底座：12 个领域、46 项能力、34 个学习单元、"
                    "确定性诊断、双语言 Runner 通路、六维证据声明和四分支入口门禁。\n\n"
                    "该版本为 `draft` 且 `intake: closed`。结构校验、Runner 测试定义和来源映射"
                    "不表示全部教学文本正确，不表示用户掌握，也不开放真实学习入口。来源实质复核、"
                    "内容抽审、运行时接线和入口启用分别留待后续已列明任务。\n",
                )
                .relative_to(PACKAGE_ROOT)
                .as_posix()
            ),
        )
    )

    graph = {
        "schema_version": "1.0.0",
        "id": "algorithm-common-core-capability-graph",
        "skill_id": "algorithm",
        "skill_version": VERSION,
        "domains": domains,
        "capabilities": [
            {
                "id": item["id"],
                "domain_id": item["domain_id"],
                "title": item["title"],
                "prerequisite_capability_ids": item["prerequisites"],
                "diagnostic_signal": item["diagnostic_signal"],
                "remediation_unit_id": item["remediation_unit_id"],
                "excludes": ["不外推到所属领域的排除项或整门算法掌握"],
            }
            for item in capabilities
        ],
    }
    generated.append(("capability_graph", "curriculum/capability-graph.yaml"))
    write_yaml(generated[-1][1], graph)

    catalog = source_catalog()
    generated.append(("source_catalog", "sources/catalog.yaml"))
    write_yaml(generated[-1][1], catalog)

    policy_spec = spec["diagnostic_policy"]
    diagnostic_policy = {
        "schema_version": "1.0.0",
        "id": "algorithm-deterministic-adaptive-diagnostic",
        "version": "1.0.0",
        "skill_id": "algorithm",
        "skill_version": VERSION,
        **{key: value for key, value in policy_spec.items() if key != "version"},
    }
    generated.append(("diagnostic_policy", "assessments/diagnostic-policy.yaml"))
    write_yaml(generated[-1][1], diagnostic_policy)

    questions: list[dict[str, Any]] = []
    question_capabilities = capabilities + capabilities[:18]
    for index, capability in enumerate(question_capabilities, start=1):
        question_id = f"diagnostic-{index:02d}-{capability['id']}"
        next_id = (
            f"diagnostic-{index + 1:02d}-{question_capabilities[index]['id']}"
            if index < len(question_capabilities)
            else None
        )
        variant = "基础判断" if index <= len(capabilities) else "独立复核"
        content_bank = (
            diagnostic_content if index <= len(capabilities) else diagnostic_followups
        )
        stem, correct_label, misconception_label = content_bank[capability["id"]]
        questions.append(
            {
                "id": question_id,
                "prompt": f"{variant}：{stem}",
                "reason": f"为能力 {capability['id']} 产生受管、可复算的诊断信号。",
                "response_type": "single_choice",
                "question_version": "1.0.0",
                "capability_ids": [capability["id"]],
                "prerequisite_capability_ids": capability["prerequisites"],
                "difficulty": "entry" if index <= 18 else "core",
                "signal_kind": "deterministic_choice",
                "deterministic_answer_values": ["scoped"],
                "critical_misconception_values": ["overclaim"],
                "selection_reason_code": "prerequisite-blocking"
                if capability["prerequisites"]
                else "entry-baseline",
                "allows_early_stop": index > 46,
                "estimated_minutes": 1,
                "source_ids": source_matrix[capability["domain_id"]][:2],
                "ambiguity_review_status": "reviewed",
                "options": [
                    {
                        "value": "scoped",
                        "label": correct_label,
                    },
                    {
                        "value": "overclaim",
                        "label": misconception_label,
                    },
                    {"value": "uncertain", "label": "不确定，保留为待补救信号"},
                ],
                "transitions": {
                    "answered": next_id,
                    "skipped": next_id,
                    "uncertain": next_id,
                },
            }
        )
    diagnostic = {
        "schema_version": "2.0.0",
        "id": "algorithm-common-core-diagnostic-bank",
        "skill_id": "algorithm",
        "skill_version": VERSION,
        "policy_id": diagnostic_policy["id"],
        "start_question_id": questions[0]["id"],
        "questions": questions,
    }
    generated.append(("diagnostic_definition", "assessments/diagnostic.yaml"))
    write_yaml(generated[-1][1], diagnostic)

    learning_units = []
    for unit in units:
        sources = source_matrix[unit["domain_id"]]
        learning_units.append(
            {
                "id": unit["id"],
                "title": unit["title"],
                "objective": f"在声明范围内理解、操作并迁移“{unit['title']}”，同时识别适用前提。",
                "reason": "按能力前置 DAG 安排，诊断缺口可映射回本单元补救。",
                "estimated_minutes": unit["estimated_minutes"],
                "prerequisite_unit_ids": unit["prerequisite_unit_ids"],
                "source_ids": sources,
                "capability_ids": unit["capability_ids"],
                "cognitive_load": "high"
                if unit["estimated_minutes"] >= 150
                else "medium",
            }
        )

    activities: list[dict[str, Any]] = []
    for domain in domains:
        domain_caps = [item["id"] for item in capabilities_by_domain[domain["id"]]]
        runner_scenario = runner_scenarios.get(domain["id"])
        runner_caps = [runner_scenario[0]] if runner_scenario else []
        for role in coverage_matrix[domain["id"]]["activity_types"]:
            scoped_caps = (
                runner_caps if role in {"runner_cpp", "runner_python"} else domain_caps
            )
            activity = activity_for_role(
                role,
                domain,
                units_by_domain[domain["id"]][0]["id"],
                scoped_caps,
                source_matrix[domain["id"]],
            )
            if role in {"runner_cpp", "runner_python"} and runner_scenario:
                activity["prompt"] = (
                    f"{runner_scenario[1]}。输出测试只验证声明的输入输出范围，"
                    "不证明复杂度、代码质量或整项能力。"
                )
            activities.append(activity)

    for unit in units:
        source_ids = source_matrix[unit["domain_id"]]
        base = {
            "unit_id": unit["id"],
            "reason": "每个学习单元都保留必需阅读与确定性检查，避免只有目录没有可执行路径。",
            "estimated_minutes": 15,
            "required": True,
            "source_ids": source_ids,
            "capability_ids": unit["capability_ids"],
            "language": "none",
        }
        activities.extend(
            [
                {
                    **base,
                    "id": f"{unit['id']}-unit-study",
                    "type": "study",
                    "title": f"{unit['title']}：来源学习",
                    "prompt": f"阅读映射来源，记录{unit['title']}的概念、前提、边界和例子。",
                    "completion_rule": "confirmation",
                    "submission_fields": [
                        {
                            "id": "confirmed",
                            "kind": "confirmation",
                            "label": "确认已完成来源学习和笔记",
                            "required": True,
                            "min_length": 0,
                            "max_length": 10,
                        }
                    ],
                    "activity_roles": ["study"],
                    "evidence_ceiling": "none",
                },
                {
                    **base,
                    "id": f"{unit['id']}-unit-check",
                    "type": "structured_check",
                    "title": f"{unit['title']}：结构检查",
                    "prompt": "完成本单元受管检查，并确认答案写明前提、步骤与限制。",
                    "completion_rule": "deterministic_pass",
                    "submission_fields": [
                        {
                            "id": "result",
                            "kind": "choice",
                            "label": "结构检查结果",
                            "required": True,
                            "min_length": 1,
                            "max_length": 20,
                            "options": ["checked", "uncertain"],
                        }
                    ],
                    "deterministic_check": {
                        "field_id": "result",
                        "accepted_values": ["checked"],
                        "feedback": "只验证受管结构，不证明自由文本技术内容正确。",
                    },
                    "activity_roles": ["structured_check"],
                    "evidence_ceiling": "supported",
                },
            ]
        )

    correction_activity_by_domain = {
        domain["id"]: f"{domain['id']}-correction" for domain in domains
    }
    remediation_rules = [
        {
            "id": f"remediate-{capability['id']}",
            "question_id": f"diagnostic-{index:02d}-{capability['id']}",
            "response_values": ["overclaim", "uncertain"],
            "activity_ids": [correction_activity_by_domain[capability["domain_id"]]],
            "reason": f"受管错误或不确定信号回到 {capability['remediation_unit_id']} 的纠错路径。",
        }
        for index, capability in enumerate(capabilities, start=1)
    ]
    learning = {
        "schema_version": "2.0.0",
        "id": "algorithm-common-core-learning",
        "skill_id": "algorithm",
        "skill_version": VERSION,
        "units": learning_units,
        "activities": activities,
        "diagnostic_remediation_rules": remediation_rules,
    }
    generated.append(("learning_definition", "curriculum/learning.yaml"))
    write_yaml(generated[-1][1], learning)

    planning = {
        "schema_version": "1.0.0",
        "id": "algorithm-common-core-planning-preview",
        "skill_id": "algorithm",
        "skill_version": VERSION,
        "title": "算法共同主干确定性规划预览",
        "rationale": "每日约两小时，按诊断缺口和前置 DAG 拆分；实际计划必须由运行时重新校验。",
        "limitations": [
            "这是关闭入口的静态预览，不创建真实学习记录。",
            "完成单元不等于掌握；分支门禁只显示资格，不自动解锁课程。",
        ],
        "units": [
            {
                "id": unit["id"],
                "title": unit["title"],
                "objective": f"完成 {unit['title']} 的学习、提取、检查、迁移与复习活动。",
                "reason": "由 8A 固定能力图和前置关系决定。",
                "estimated_minutes": min(unit["estimated_minutes"], 180),
                "completion_criteria": [
                    "完成所有必需活动并保留原始证据等级",
                    "阻断复核、来源待办和保持待办不覆盖原证据",
                ],
                "source_ids": source_matrix[unit["domain_id"]],
            }
            for unit in units
        ],
    }
    generated.append(("planning_template", "curriculum/planning-preview.yaml"))
    write_yaml(generated[-1][1], planning)

    runner_tasks = []
    for activity in activities:
        if activity["completion_rule"] != "runner_pass":
            continue
        language = activity["language"]
        domain_id = activity["id"].split("-", maxsplit=1)[0]
        runner_scenario = runner_scenarios[domain_id]
        runner_tasks.append(
            {
                "id": activity["runner_task_id"],
                "activity_id": activity["id"],
                "runtime_profile_id": "cpp-gcc-15-2"
                if language == "cpp"
                else "python-3-14-3",
                "runtime_profile_version": "1.0.0",
                "language": language,
                "source_field_id": "source",
                "capability_ids": activity["capability_ids"],
                "tests": [
                    {
                        "id": case_id,
                        "stdin": stdin,
                        "expected_stdout": stdout,
                        "purpose": f"{case_id} 代表用例",
                    }
                    for case_id, stdin, stdout in runner_scenario[2]
                ],
            }
        )
    runner = {
        "schema_version": "2.0.0",
        "id": "algorithm-common-core-runner-tasks",
        "skill_id": "algorithm",
        "skill_version": VERSION,
        "tasks": runner_tasks,
    }
    generated.append(("runner_task_definition", "assessments/runner-tasks.yaml"))
    write_yaml(generated[-1][1], runner)

    role_for_dimension = {
        "understanding": "structured_check",
        "operation": "runner_cpp",
        "transfer": "transfer",
        "artifact": "project",
        "retention": "review",
        "correction": "correction",
    }
    criteria = []
    for domain in domains:
        coverage = coverage_matrix[domain["id"]]
        for dimension in coverage["evidence_dimensions"]:
            role = role_for_dimension[dimension]
            activity_id = f"{domain['id']}-{role.replace('_', '-')}"
            activity = next(item for item in activities if item["id"] == activity_id)
            method = {
                "understanding": "deterministic",
                "operation": "runner",
                "transfer": "self_review",
                "artifact": "self_review",
                "retention": "review_pending",
                "correction": "deterministic",
            }[dimension]
            criterion = {
                "id": f"{domain['id']}-{dimension}-criterion",
                "activity_id": activity_id,
                "description": f"只评价{domain['title']}中已声明能力的 {dimension} 维度。",
                "dimension": dimension,
                "evaluation_method": method,
                "passing_result": "passed"
                if method in {"deterministic", "runner"}
                else "submitted",
                "evidence_strength": {
                    "understanding": "supported",
                    "operation": "verified",
                    "transfer": "limited",
                    "artifact": "limited",
                    "retention": "retained_limited",
                    "correction": "supported",
                }[dimension],
                "review_flags": []
                if method in {"deterministic", "runner"}
                else ["manual_review_pending"],
                "capability_ids": activity["capability_ids"],
                "language": activity["language"],
            }
            if method == "self_review":
                criterion["self_review_rubric_id"] = f"{dimension}-rubric"
            criteria.append(criterion)
    assessment = {
        "schema_version": "2.0.0",
        "id": "algorithm-common-core-assessment",
        "skill_id": "algorithm",
        "skill_version": VERSION,
        "criteria": criteria,
    }
    generated.append(("assessment_definition", "assessments/assessment.yaml"))
    write_yaml(generated[-1][1], assessment)

    rubrics = {
        "schema_version": "1.0.0",
        "id": "algorithm-common-core-rubrics",
        "skill_id": "algorithm",
        "skill_version": VERSION,
        "criteria": [
            {
                "id": f"{dimension}-rubric",
                "title": f"{dimension} 受管范围观察量表",
                "prompt": (
                    "是否在精确能力范围内给出了可观察步骤、明确假设、边界或反例，"
                    "并限制结论范围？记录必须另行标明自评或外部真人评审。"
                ),
                "levels": [
                    {
                        "value": "not_yet",
                        "label": "尚未满足",
                        "observable_description": "缺少两个以上要素。",
                    },
                    {
                        "value": "uncertain",
                        "label": "不确定",
                        "observable_description": "结构存在但技术内容需要复核。",
                    },
                    {
                        "value": "meets",
                        "label": "观察项满足",
                        "observable_description": (
                            "结构要素齐全；自评仍只是有限证据，只有精确范围的外部真人评审"
                            "才属于独立验证。"
                        ),
                    },
                ],
            }
            for dimension in [
                "understanding",
                "operation",
                "transfer",
                "artifact",
                "retention",
                "correction",
            ]
        ],
    }
    generated.append(("rubric_definition", "assessments/rubric.yaml"))
    write_yaml(generated[-1][1], rubrics)

    review = {
        "schema_version": "1.0.0",
        "id": "algorithm-common-core-fixed-review",
        "version": "1.0.0",
        "skill_id": "algorithm",
        "skill_version": VERSION,
        "strategy": "fixed_expanding",
        "interval_days": [1, 2, 4, 7, 15],
        "failure_retry_days": 1,
        "missed_task_behavior": "overdue_not_failure",
        "completion_checkpoint": 5,
        "source_ids": ["spacing-research-set", "ies-study-guide"],
        "limitations": [
            "固定间隔是透明产品规则，不是对每个人都最优的遗忘曲线。",
            "失败时保持 retention_pending，追加纠错和新复习；完成不表示整体掌握。",
        ],
    }
    generated.append(("review_policy", "review/policy.yaml"))
    write_yaml(generated[-1][1], review)

    mastery = {
        "schema_version": "1.0.0",
        "id": "algorithm-common-core-mastery-scope",
        "skill_id": "algorithm",
        "skill_version": VERSION,
        "scope_statement": "只评价 12 域共同主干中精确能力、活动、语言和测试范围的证据。",
        "dimensions": [
            "understanding",
            "operation",
            "transfer",
            "artifact",
            "retention",
            "correction",
        ],
        "allowed_evidence_levels": [
            "limited",
            "supported",
            "retained_limited",
            "verified",
            "retained",
        ],
        "prohibited_claims": ["scope_criteria_met", "mastered"],
        "limitations": [
            "verified 仅表示锁定 Runner 中对应任务的完整确定性测试通过。",
            "retained 仅表示延迟后的同范围 Runner 复测通过，不表示永久保持。",
            "结构校验、自由文本、自评和流程完成均不证明整门算法掌握。",
        ],
    }
    generated.append(("mastery_scope", "assessments/mastery-scope.yaml"))
    write_yaml(generated[-1][1], mastery)

    branch_gates: dict[str, Any] = {
        "schema_version": "1.0.0",
        "id": "algorithm-common-core-branch-gates",
        "version": "1.0.0",
        "skill_id": "algorithm",
        "skill_version": VERSION,
        "gates": [],
    }
    gate_titles = {
        "engineering": "工程应用",
        "interview": "求职面试",
        "competition": "算法竞赛",
        "theory": "算法理论",
    }
    for gate in spec["branch_gates"]:
        theory = gate["id"] == "theory"
        branch_gates["gates"].append(
            {
                "id": gate["id"],
                "title": gate_titles[gate["id"]],
                "required_capability_ids": gate["required_capability_ids"],
                "minimum_levels": {
                    "understanding": "supported",
                    "operation": "verified" if not theory else "supported",
                },
                "required_retained_count": 0 if theory else 2,
                "independent_review_dimensions": ["understanding"] if theory else [],
                "blocking_review_flags": [
                    "manual_review_pending",
                    "retention_due",
                    "source_review_pending",
                    "version_mismatch",
                ],
                "limitations": [
                    gate["required"],
                    "门禁只计算入口状态，不创建课程，也不表示整门算法掌握。",
                ],
            }
        )
    generated.append(("branch_gate_policy", "assessments/branch-gates.yaml"))
    write_yaml(generated[-1][1], branch_gates)

    runner_caps_by_domain = {
        domain["id"]: (
            [runner_scenarios[domain["id"]][0]]
            if f"{domain['id']}-runner-cpp" in {a["id"] for a in activities}
            else []
        )
        for domain in domains
    }
    coverage = {
        "schema_version": "1.0.0",
        "id": "algorithm-common-core-content-coverage",
        "skill_id": "algorithm",
        "skill_version": VERSION,
        "budgets": {
            "domain_count": spec["content_budget"]["exact_domains"],
            "capability_max": spec["content_budget"]["max_capabilities"],
            "unit_max": spec["content_budget"]["max_units"],
            "total_unit_minutes_max": spec["content_budget"]["max_total_unit_minutes"],
            "diagnostic_item_max": spec["content_budget"]["max_diagnostic_items"],
            "runner_task_max": spec["content_budget"]["max_runner_tasks"],
            "rubric_max": spec["content_budget"]["max_rubrics"],
        },
        "domains": [
            {
                "domain_id": domain["id"],
                "source_ids": source_matrix[domain["id"]],
                "required_activity_roles": coverage_matrix[domain["id"]][
                    "activity_types"
                ],
                "evidence_dimensions": coverage_matrix[domain["id"]][
                    "evidence_dimensions"
                ],
                "runner_capability_ids": runner_caps_by_domain[domain["id"]],
            }
            for domain in domains
        ],
    }
    generated.append(("content_coverage", "curriculum/content-coverage.yaml"))
    write_yaml(generated[-1][1], coverage)

    manifest = {
        "schema_version": "1.1.0",
        "id": "algorithm",
        "version": VERSION,
        "title": "算法共同主干完整学习核心草稿",
        "state": "draft",
        "availability": "available",
        "engine_contract": {"version": ">=0.4.0 <0.5.0"},
        "runner_protocol": {"version": "1.1.0"},
        "runtime_profiles": [
            {"id": "cpp-gcc-15-2", "version": "1.0.0"},
            {"id": "python-3-14-3", "version": "1.0.0"},
        ],
        "skill_dependencies": [],
        "content_files": [
            {"kind": kind, "path": path, "sha256": sha256(PACKAGE_ROOT / path)}
            for kind, path in generated
        ],
        "sources": [
            {
                "id": "milestone-8a-spec",
                "title": "里程碑 8A 学习核心机器规格",
                "url": "https://local.cloud-study/docs/architecture/milestone-8a-spec",
                "retrieved_at": TODAY,
            }
        ],
    }
    manifest_path = write_yaml("manifest.yaml", manifest)

    registry_path = ROOT / "skill-packs" / "registry.yaml"
    registry = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    registry["packages"] = [
        item
        for item in registry["packages"]
        if not (item["id"] == "algorithm" and item["version"] == VERSION)
    ]
    registry["packages"].append(
        {
            "id": "algorithm",
            "version": VERSION,
            "path": "skill-packs/algorithm/versions/0.3.0",
            "state": "draft",
            "availability": "available",
            "intake": "closed",
            "manifest_sha256": sha256(manifest_path),
        }
    )
    registry_path.write_text(
        yaml.dump(
            registry,
            Dumper=IndentedSafeDumper,
            allow_unicode=True,
            sort_keys=False,
            width=100,
        ),
        encoding="utf-8",
        newline="\n",
    )


if __name__ == "__main__":
    build()
