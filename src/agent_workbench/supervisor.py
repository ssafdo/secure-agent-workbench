from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from .agents import ResearchAgent, ResearchReport, RetrievalResearchAgent
from .runtime import AgentRuntime


class ResearchSpecialist(StrEnum):
    SYNTHESIS = "synthesis"
    RETRIEVAL = "retrieval"


class RoutingConfidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass(frozen=True)
class RoutingDecision:
    specialist: ResearchSpecialist
    reason: str
    signal_count: int
    confidence: RoutingConfidence
    synthesis_signal_count: int
    retrieval_signal_count: int

    def response(self) -> dict[str, str | int]:
        return {
            "specialist": self.specialist.value,
            "reason": self.reason,
            "signalCount": self.signal_count,
            "confidence": self.confidence.value,
            "synthesisSignalCount": self.synthesis_signal_count,
            "retrievalSignalCount": self.retrieval_signal_count,
        }


@dataclass(frozen=True)
class SupervisedResearchReport:
    report: ResearchReport
    routing: RoutingDecision


_STRONG_SYNTHESIS_PATTERNS = (
    re.compile(r"\b(?:all|every)\s+(?:source|document|file)s?\b", re.IGNORECASE),
    re.compile(
        r"\b(?:across|between)\s+(?:the\s+)?(?:sources?|documents?|files?|notes?|papers?|reports?|studies)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:cross-document|multi-document|literature review|research review)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:compare|contrast|comparison|differences?|similarities)\b.{0,80}\b(?:sources?|documents?|files?|proposals?|reports?|studies|papers?)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:sources?|documents?|files?|proposals?|reports?|studies|papers?|materials?|notes?)\b.{0,100}\b(?:compare|contrast|comparison|differences?|similarities|summari[sz]e|synthesi[sz]e|integrate)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:consolidated|project)\s+(?:briefing|digest|summary|overview)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bsummari[sz]e\s+(?:the\s+)?(?:project|sources?|documents?|files?|collection|materials?)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:write|draft|prepare|produce|create|turn|organize|synthesi[sz]e)\b.{0,80}\b(?:abstract|article|briefing|digest|literature review|manuscript|memo|overview|paper|report|review|summary)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:summari[sz]e|synthesi[sz]e|integrate)\b.{0,80}\b(?:findings?|notes?|research|results?|studies)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:analy[sz]e|review)\b.{0,80}\b(?:patterns?|results?|trends?)\b.{0,80}\b(?:notes?|reports?|studies)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:analy[sz]e|review)\b.{0,80}\b(?:notes?|reports?|studies)\b.{0,80}\b(?:patterns?|results?|trends?)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:review|assess|analy[sz]e)\b.{0,80}\b(?:supplied|provided|attached)\s+(?:materials?|documents?|files?|notes?|reports?)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:complete|comprehensive|detailed|in-depth|full)\b.{0,80}\b(?:analysis|assessment|briefing|guide|overview|plan|report|review|roadmap|strategy|summary)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:write|draft|prepare|produce|create|organize|develop)\b.{0,80}\b(?:course|framework|guide|lesson|manual|plan|presentation|proposal|roadmap|strategy|tutorial)\b",
        re.IGNORECASE,
    ),
    re.compile(r"(?:全部|所有|各份|多份)(?:资料|文档|文件)"),
    re.compile(r"(?:跨|贯穿)(?:资料|文档|文件)"),
    re.compile(r"(?:整体|综合|全局)(?:总结|汇总|概览|综述|盘点|简报)"),
    re.compile(r"(?:比较|对比|异同).*(?:资料|文档|文件)"),
    re.compile(r"(?:资料|文档|文件|报告).{0,40}(?:比较|对比|异同)"),
    re.compile(r"(?:两|三|四|五|六|七|八|九|十|\d+)份(?:资料|文档|文件|报告|方案)"),
    re.compile(r"(?:写|撰写|编写|准备|整理|形成|生成).{0,40}(?:摘要|文章|简报|综述|报告|论文|文稿|备忘录|概览)(?!前|后|时|需要)"),
    re.compile(r"(?:总结|汇总|综述|整合).{0,40}(?:发现|结果|研究|资料|材料|笔记|记录)"),
    re.compile(r"(?:整合成|汇总成).{0,40}(?:总结|报告|简报|综述)"),
    re.compile(r"(?:分析|审阅).{0,40}(?:趋势|变化|结果|规律).{0,40}(?:报告|资料|记录)"),
    re.compile(
        r"(?:分析|审阅).{0,40}(?:各月|历年|多份|多个|一系列)(?:报告|资料|记录).{0,40}(?:趋势|变化|结果|规律)"
    ),
    re.compile(r"(?:审阅|评估|分析).{0,40}(?:提供|给定|附带|上传)(?:的)?(?:资料|文档|文件|笔记|报告|材料)"),
    re.compile(r"(?:完整|全面|详细|深入).{0,40}(?:分析|评估|简报|指南|概览|计划|报告|综述|路线图|策略|总结)"),
    re.compile(r"(?:写|撰写|编写|准备|制定|形成|生成|整理).{0,40}(?:课程|框架|指南|教案|手册|计划|演示|方案|路线图|策略|教程)"),
    re.compile(r"(?:前人研究|研究进展|文献回顾|文献综述|研究综述)"),
)
_STRUCTURED_SYNTHESIS_PATTERNS = (
    re.compile(
        r"\b(?:expected|anticipated)\b.{0,40}\b(?:outcomes?|results?|deliverables?)\b.{0,120}\b(?:interim|milestone|phase|final)\s+(?:outcomes?|results?|deliverables?)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:create|design|develop|prepare)\b.{0,50}\b(?:framework|plan|proposal|roadmap|strategy)\b.{0,120}\b(?:criteria|evaluation|limitations?|methods?|objectives?|results?)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:build|construct|design|implement|set up)\b.{0,120}\b(?:analy[sz]e|assess|evaluate|observe|validate)\b.{0,120}\b(?:affect|effect|impact|performance|relationship|results?)\b",
        re.IGNORECASE,
    ),
    re.compile(r"(?:预期成果|预期结果).{0,80}(?:阶段性|中期|最终|结题)(?:成果|结果)"),
    re.compile(r"(?:阶段性|中期)(?:成果|结果).{0,80}(?:最终|结题)(?:成果|结果)"),
    re.compile(
        r"(?:围绕|根据|基于).{0,30}(?:目标|内容|方法|技术路线).{0,100}(?:设计|形成|制定|构建).{0,40}(?:方案|框架|计划|策略)"
    ),
    re.compile(
        r"(?:搭建|构建|建立|设计|实现).{0,100}(?:观察|分析|评估|评价|验证|比较|优化).{0,100}(?:影响|关系|结果|性能|效果|趋势|分配)"
    ),
)
_CHINESE_STRUCTURED_SECTION_TERMS = (
    "背景",
    "现状",
    "目标",
    "内容",
    "方法",
    "技术路线",
    "方案",
    "步骤",
    "策略",
    "成果",
    "总结",
    "评价",
    "评估",
    "结果",
    "结论",
    "建议",
    "风险",
    "措施",
    "局限",
    "讨论",
)
_CHINESE_STRUCTURED_ACTION_TERMS = (
    "制定",
    "设计",
    "构建",
    "搭建",
    "建立",
    "形成",
    "撰写",
    "编写",
    "生成",
    "整理",
    "分析",
    "评估",
    "评价",
    "总结",
    "归纳",
    "比较",
    "研究",
)
_STRONG_RETRIEVAL_PATTERNS = (
    re.compile(
        r"\b(?:cite|citation|evidence|verify|find|locate|quote|identify|extract|according to|pull out)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\b(?:check whether|tell me|source says?|document states?)\b", re.IGNORECASE),
    re.compile(r"\bwhich\s+(?:source|document|file)\b", re.IGNORECASE),
    re.compile(r"\b(?:exact sentence|only need (?:the )?name|name of the)\b", re.IGNORECASE),
    re.compile(r"(?:引用|证据|查找|查证|核实|摘录|根据资料|哪份文档|哪一行)"),
    re.compile(
        r"(?:请|帮我|从.{0,20})?提取.{0,30}(?:原文|句子|字段|信息|名称|数据|数字|日期|条款)"
    ),
    re.compile(r"定位.{0,30}(?:文档|文件|资料|原文|条款|位置)"),
)
_WEAK_RETRIEVAL_PATTERNS = (
    re.compile(r"\b(?:which|what|where|when|who|how|why|does|do|is|are|can)\b", re.IGNORECASE),
    re.compile(r"(?:什么|哪里|何时|谁|如何|怎么|为什么|为何|是否|能否|有何)"),
    re.compile(r"[?？]"),
)
_ROUTING_MANIPULATION_PATTERNS = (
    re.compile(
        r"\b(?:ignore|bypass|override)\b.{0,80}\b(?:agent|policy|router|routing|supervisor)\b",
        re.IGNORECASE,
    ),
    re.compile(r"(?:忽略|绕过|覆盖).{0,40}(?:代理|智能体|策略|路由|主管)"),
)


class ResearchSupervisor:
    """Routes a task to one bounded specialist without owning any tools."""

    def __init__(self, runtime: AgentRuntime) -> None:
        self.runtime = runtime

    @staticmethod
    def _structured_synthesis_signals(task: str) -> int:
        pattern_signals = sum(
            bool(pattern.search(task)) for pattern in _STRUCTURED_SYNTHESIS_PATTERNS
        )
        if not re.search(r"[\u3400-\u9fff]", task):
            return pattern_signals
        section_count = sum(term in task for term in _CHINESE_STRUCTURED_SECTION_TERMS)
        action_count = sum(term in task for term in _CHINESE_STRUCTURED_ACTION_TERMS)
        has_structured_scope = (
            len(task) >= 120 and section_count >= 3 and action_count >= 2
        ) or (len(task) >= 240 and section_count >= 2 and action_count >= 2)
        return pattern_signals + int(has_structured_scope)

    @staticmethod
    def route(task: str) -> RoutingDecision:
        normalized = " ".join(task.split())
        if not normalized:
            raise ValueError("Research task cannot be empty.")
        cross_source_synthesis_signals = sum(
            bool(pattern.search(normalized)) for pattern in _STRONG_SYNTHESIS_PATTERNS
        )
        structured_synthesis_signals = ResearchSupervisor._structured_synthesis_signals(
            normalized
        )
        synthesis_signals = (
            cross_source_synthesis_signals + structured_synthesis_signals
        )
        strong_retrieval_signals = sum(
            bool(pattern.search(normalized)) for pattern in _STRONG_RETRIEVAL_PATTERNS
        )
        weak_retrieval_signals = sum(
            bool(pattern.search(normalized)) for pattern in _WEAK_RETRIEVAL_PATTERNS
        )
        routing_manipulation_signals = sum(
            bool(pattern.search(normalized))
            for pattern in _ROUTING_MANIPULATION_PATTERNS
        )
        retrieval_signals = strong_retrieval_signals + weak_retrieval_signals
        if cross_source_synthesis_signals:
            return RoutingDecision(
                ResearchSpecialist.SYNTHESIS,
                "cross-source-synthesis",
                synthesis_signals,
                (
                    RoutingConfidence.MEDIUM
                    if retrieval_signals
                    else RoutingConfidence.HIGH
                ),
                synthesis_signals,
                retrieval_signals,
            )
        if structured_synthesis_signals:
            return RoutingDecision(
                ResearchSpecialist.SYNTHESIS,
                "structured-synthesis",
                structured_synthesis_signals,
                (
                    RoutingConfidence.MEDIUM
                    if retrieval_signals
                    else RoutingConfidence.HIGH
                ),
                synthesis_signals,
                retrieval_signals,
            )
        if strong_retrieval_signals:
            return RoutingDecision(
                ResearchSpecialist.RETRIEVAL,
                "evidence-grounded-query",
                strong_retrieval_signals,
                RoutingConfidence.HIGH,
                synthesis_signals,
                retrieval_signals,
            )
        if weak_retrieval_signals:
            return RoutingDecision(
                ResearchSpecialist.RETRIEVAL,
                "direct-question",
                weak_retrieval_signals,
                RoutingConfidence.MEDIUM,
                synthesis_signals,
                retrieval_signals,
            )
        if routing_manipulation_signals:
            return RoutingDecision(
                ResearchSpecialist.SYNTHESIS,
                "conservative-default",
                0,
                RoutingConfidence.LOW,
                synthesis_signals,
                retrieval_signals,
            )
        return RoutingDecision(
            ResearchSpecialist.RETRIEVAL,
            "bounded-default",
            0,
            RoutingConfidence.LOW,
            synthesis_signals,
            retrieval_signals,
        )

    def run(self, task: str, approve_write: bool = False) -> SupervisedResearchReport:
        decision = self.route(task)
        self.runtime.record_agent_route(
            supervisor="research",
            specialist=decision.specialist.value,
            reason=decision.reason,
            signal_count=decision.signal_count,
            confidence=decision.confidence.value,
            synthesis_signal_count=decision.synthesis_signal_count,
            retrieval_signal_count=decision.retrieval_signal_count,
        )
        if decision.specialist is ResearchSpecialist.RETRIEVAL:
            report = RetrievalResearchAgent(self.runtime).run(
                task, approve_write=approve_write
            )
        else:
            report = ResearchAgent(self.runtime).run(task, approve_write=approve_write)
        return SupervisedResearchReport(report, decision)
