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
        r"\b(?:analy[sz]e|review)\b.{0,80}\b(?:patterns?|results?|trends?)\b.{0,80}\b(?:notes?|reports?|studies)?\b",
        re.IGNORECASE,
    ),
    re.compile(r"(?:全部|所有|各份|多份)(?:资料|文档|文件)"),
    re.compile(r"(?:跨|贯穿)(?:资料|文档|文件)"),
    re.compile(r"(?:整体|综合|全局)(?:总结|汇总|概览|综述|盘点|简报)"),
    re.compile(r"(?:比较|对比|异同).*(?:资料|文档|文件)"),
    re.compile(r"(?:资料|文档|文件|报告).{0,40}(?:比较|对比|异同)"),
    re.compile(r"(?:两|三|四|五|六|七|八|九|十|\d+)份(?:资料|文档|文件|报告|方案)"),
    re.compile(r"(?:写|撰写|编写|整理|形成|生成).{0,40}(?:摘要|文章|简报|综述|报告|论文|文稿|备忘录|概览)(?!前|后|时|需要)"),
    re.compile(r"(?:总结|汇总|综述|整合).{0,40}(?:发现|结果|研究|资料|材料|笔记|记录)"),
    re.compile(r"(?:整合成|汇总成).{0,40}(?:总结|报告|简报|综述)"),
    re.compile(r"(?:分析|审阅).{0,40}(?:趋势|变化|结果|规律).{0,40}(?:报告|资料|记录)?"),
    re.compile(r"(?:前人研究|研究进展|文献回顾|文献综述|研究综述)"),
)
_STRONG_RETRIEVAL_PATTERNS = (
    re.compile(
        r"\b(?:cite|citation|evidence|verify|find|locate|quote|identify|extract|according to|pull out)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\b(?:check whether|tell me|source says?|document states?)\b", re.IGNORECASE),
    re.compile(r"\bwhich\s+(?:source|document|file)\b", re.IGNORECASE),
    re.compile(r"\b(?:exact sentence|only need (?:the )?name|name of the)\b", re.IGNORECASE),
    re.compile(r"(?:引用|证据|查找|查证|核实|定位|摘录|提取|根据资料|哪份文档|哪一行)"),
)
_WEAK_RETRIEVAL_PATTERNS = (
    re.compile(r"\b(?:which|what|where|when|who|how|why|does|do|is|are|can)\b", re.IGNORECASE),
    re.compile(r"(?:什么|哪里|何时|谁|如何|怎么|为什么|为何|是否|能否|有何)"),
    re.compile(r"[?？]"),
)


class ResearchSupervisor:
    """Routes a task to one bounded specialist without owning any tools."""

    def __init__(self, runtime: AgentRuntime) -> None:
        self.runtime = runtime

    @staticmethod
    def route(task: str) -> RoutingDecision:
        normalized = " ".join(task.split())
        if not normalized:
            raise ValueError("Research task cannot be empty.")
        synthesis_signals = sum(
            bool(pattern.search(normalized)) for pattern in _STRONG_SYNTHESIS_PATTERNS
        )
        strong_retrieval_signals = sum(
            bool(pattern.search(normalized)) for pattern in _STRONG_RETRIEVAL_PATTERNS
        )
        weak_retrieval_signals = sum(
            bool(pattern.search(normalized)) for pattern in _WEAK_RETRIEVAL_PATTERNS
        )
        retrieval_signals = strong_retrieval_signals + weak_retrieval_signals
        if synthesis_signals:
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
        return RoutingDecision(
            ResearchSpecialist.SYNTHESIS,
            "conservative-default",
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
