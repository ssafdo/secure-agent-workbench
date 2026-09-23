from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from .agents import ResearchAgent, ResearchReport, RetrievalResearchAgent
from .runtime import AgentRuntime


class ResearchSpecialist(StrEnum):
    SYNTHESIS = "synthesis"
    RETRIEVAL = "retrieval"


@dataclass(frozen=True)
class RoutingDecision:
    specialist: ResearchSpecialist
    reason: str
    signal_count: int

    def response(self) -> dict[str, str | int]:
        return {
            "specialist": self.specialist.value,
            "reason": self.reason,
            "signalCount": self.signal_count,
        }


@dataclass(frozen=True)
class SupervisedResearchReport:
    report: ResearchReport
    routing: RoutingDecision


_SYNTHESIS_PATTERNS = (
    re.compile(r"\b(?:all|every)\s+(?:source|document|file)s?\b", re.IGNORECASE),
    re.compile(r"\b(?:overview|inventory|compare|cross-document)\b", re.IGNORECASE),
    re.compile(r"\bsummari[sz]e\s+(?:the\s+)?(?:project|sources|documents|files)\b", re.IGNORECASE),
    re.compile(r"(?:全部|所有)(?:资料|文档|文件)"),
    re.compile(r"(?:整体|综合)(?:总结|汇总|概览)"),
    re.compile(r"(?:比较|对比).*(?:资料|文档|文件)"),
)
_RETRIEVAL_PATTERNS = (
    re.compile(r"\b(?:cite|citation|evidence|verify|find|locate|according to)\b", re.IGNORECASE),
    re.compile(r"\b(?:which|what|where|when|who|how)\b", re.IGNORECASE),
    re.compile(r"(?:引用|证据|查找|查证|核实|根据资料|哪份文档|哪一行)"),
    re.compile(r"(?:什么|哪里|何时|谁|如何|怎么|是否)"),
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
            bool(pattern.search(normalized)) for pattern in _SYNTHESIS_PATTERNS
        )
        retrieval_signals = sum(
            bool(pattern.search(normalized)) for pattern in _RETRIEVAL_PATTERNS
        )
        if synthesis_signals:
            return RoutingDecision(
                ResearchSpecialist.SYNTHESIS,
                "cross-source-synthesis",
                synthesis_signals,
            )
        if retrieval_signals:
            return RoutingDecision(
                ResearchSpecialist.RETRIEVAL,
                "evidence-grounded-query",
                retrieval_signals,
            )
        return RoutingDecision(
            ResearchSpecialist.SYNTHESIS,
            "conservative-default",
            0,
        )

    def run(self, task: str, approve_write: bool = False) -> SupervisedResearchReport:
        decision = self.route(task)
        self.runtime.record_agent_route(
            supervisor="research",
            specialist=decision.specialist.value,
            reason=decision.reason,
            signal_count=decision.signal_count,
        )
        if decision.specialist is ResearchSpecialist.RETRIEVAL:
            report = RetrievalResearchAgent(self.runtime).run(
                task, approve_write=approve_write
            )
        else:
            report = ResearchAgent(self.runtime).run(task, approve_write=approve_write)
        return SupervisedResearchReport(report, decision)
