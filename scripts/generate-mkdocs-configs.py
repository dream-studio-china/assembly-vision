#!/usr/bin/env python3
"""Generate mkdocs-en.yml (site/) and mkdocs-zh.yml (site/zh/) from mkdocs.yml.

This is the config-generation step of the bilingual build. It:

- Loads the master `mkdocs.yml`, preserving the `!!python/name:...` Mermaid
  superfences tag through a custom PyYAML loader/dumper.
- Sets per-language site_dir / site_url / docs_dir / theme language.
- Translates navigation labels (static map, then Google fallback).
- Writes the `extra.alternate` language switcher for both configs.

Usage:
    python scripts/generate-mkdocs-configs.py
"""

import copy
from pathlib import Path
from urllib.parse import urlparse

import yaml

ROOT = Path(__file__).resolve().parent.parent


class NameTag:
    """Holds the raw string of a !!python/name: tag so it round-trips."""

    def __init__(self, name: str) -> None:
        self.name = name


class _Loader(yaml.SafeLoader):
    pass


class _Dumper(yaml.SafeDumper):
    pass


def _load_name(loader: _Loader, suffix: str, node) -> NameTag:
    return NameTag(suffix)


def _dump_name(dumper: _Dumper, data: NameTag):
    # PyYAML's construct_python_name requires the name in the TAG suffix and an
    # empty scalar value: `!!python/name:pymdownx.superfences.fence_code_format`
    return dumper.represent_scalar("tag:yaml.org,2002:python/name:" + data.name, "")


_Loader.add_multi_constructor("tag:yaml.org,2002:python/name:", _load_name)
_Dumper.add_representer(NameTag, _dump_name)

# Static English -> Chinese nav label map. Add new labels here instead of relying
# on the Google fallback (fewer API calls, deterministic output).
MAP = {
    "Home": "首页",
    "Source Brief": "原始需求",
    "Architecture Design": "架构设计",
    "Design Index": "设计索引",
    "Cover and Status": "封面与状态",
    "Introduction": "简介",
    "Requirements": "需求",
    "Architecture Overview": "架构概览",
    "Edge Client Architecture": "边缘端架构",
    "Central Server Architecture": "中心端架构",
    "AI Detection Pipeline": "AI 检测流水线",
    "Camera and Image Acquisition": "相机与图像采集",
    "Product Detection and ROI": "产品检测与 ROI",
    "Component Detection": "组件检测",
    "Temporal Aggregation": "时序聚合",
    "Rule Engine": "规则引擎",
    "Local Storage and Retention": "本地存储与保留",
    "Upload and Synchronization": "上传与同步",
    "Data Model and Database": "数据模型与数据库",
    "REST API and Events": "REST API 与事件",
    "Edge Dashboard": "边缘端看板",
    "Central Admin Dashboard": "中心管理看板",
    "Monorepo and Code Organization": "Monorepo 与代码组织",
    "Training and Evaluation": "训练与评估",
    "Deployment and Operations": "部署与运维",
    "Security and Source Distribution": "安全与源码分发",
    "Testing and Quality Assurance": "测试与质量保证",
    "Observability and Support": "可观测性与支持",
    "Human in the Loop": "人在回路",
    "Roadmap": "路线图",
    "Customer Acceptance": "客户验收",
    "Risks and Mitigations": "风险与缓解",
    "Appendices": "附录",
    "Architecture Decisions": "架构决策",
    "ADR Index": "ADR 索引",
    "ADR-001: Edge-First Inspection": "ADR-001：边缘优先检测",
    "ADR-002: Python Backend": "ADR-002：Python 后端",
    "ADR-003: Vue 3 and TypeScript Frontend": "ADR-003：Vue 3 与 TypeScript 前端",
    "ADR-004: Two-Stage Detection": "ADR-004：两阶段检测",
    "ADR-005: Local-First Storage and Delayed Upload": "ADR-005：本地优先存储与延迟上传",
    "ADR-006: REST Plus WebSocket": "ADR-006：REST 与 WebSocket",
    "ADR-007: Monorepo": "ADR-007：Monorepo",
    "ADR-008: Docker Deployment": "ADR-008：Docker 部署",
    "ADR-009: Static-Image-First MVP": "ADR-009：静态图像优先 MVP",
    "ADR-010: Per-Component Temporal Aggregation": "ADR-010：按组件时序聚合",
    "Engineering Contracts": "工程合同",
    "Contract Index": "合同索引",
    "Architecture Boundaries": "架构边界",
    "Code and Interface Contracts": "代码与接口合同",
    "AI, Rule Engine, and Fail-Safe Contracts": "AI、规则引擎与故障安全合同",
    "Edge, Storage, and Upload Contracts": "边缘端、存储与上传合同",
    "Data, API, and Versioning Contracts": "数据、API 与版本合同",
    "Testing, Quality, and CI Contracts": "测试、质量与 CI 合同",
    "Deployment, Observability, and Operations": "部署、可观测性与运维",
    "Security, Permissions, and Audit": "安全、权限与审计",
    "Industrial Site and Change Control": "工业现场与变更控制",
    "Model, Rule, Release, and Acceptance": "模型、规则、发布与验收",
    "Minimum Mandatory Contracts": "最低强制合同",
    "Operational Runbooks": "运维手册",
    "Runbook Index": "运行手册索引",
    "Camera Disconnection": "相机断开",
    "Model-Loading Failure": "模型加载失败",
    "Low Disk Space": "磁盘空间不足",
    "Upload Backlog": "上传积压",
    "Database Recovery": "数据库恢复",
    "Repeated Container Restart": "容器反复重启",
    "Network Recovery Synchronization": "网络恢复同步",
    "Model Rollback": "模型回滚",
    "Rule Rollback": "规则回滚",
    "Research": "调研",
    "Industrial Inspection Success Rates": "工业检测成功率",
    "YOLO Capabilities and Success Rates": "YOLO 能力与成功率",
    "Imaging Workflow and Training Cost": "成像流程与训练成本",
    "Contributor Documentation": "贡献者文档",
    "Contributing": "贡献指南",
    "AI Context Snapshot": "AI 上下文快照",
}


def tr(s: str) -> str:
    if s in MAP:
        return MAP[s]
    if len(s) < 60 and " " in s:
        try:
            from deep_translator import GoogleTranslator

            translated = GoogleTranslator(source="en", target="zh-CN").translate(s)
        except Exception:
            translated = None
        if translated:
            MAP[s] = translated
            return translated
    return s


def walk(items) -> None:
    for item in items:
        if isinstance(item, dict):
            for key in list(item.keys()):
                new_key = tr(key)
                if new_key != key:
                    item[new_key] = item.pop(key)
                value = item[new_key]
                if isinstance(value, list):
                    walk(value)


def main() -> None:
    # `_Loader` subclasses yaml.SafeLoader and only captures the `!!python/name:`
    # tag suffix as a string; it never instantiates arbitrary objects.
    cfg = yaml.load((ROOT / "mkdocs.yml").read_text(encoding="utf-8"), Loader=_Loader)  # noqa: S506

    site_url = cfg.get("site_url", "")
    path = urlparse(site_url).path.rstrip("/") if site_url else ""

    alternates = [
        {"name": "English", "link": path + "/", "lang": "en"},
        {"name": "中文", "link": path + "/zh/", "lang": "zh"},
    ]

    en_cfg = copy.deepcopy(cfg)
    en_cfg.setdefault("extra", {})["alternate"] = alternates
    (ROOT / "mkdocs-en.yml").write_text(
        yaml.dump(
            en_cfg, Dumper=_Dumper, allow_unicode=True, default_flow_style=False, sort_keys=False
        ),
        encoding="utf-8",
    )

    zh_cfg = copy.deepcopy(en_cfg)
    zh_cfg["docs_dir"] = "docs-zh"
    zh_cfg["site_dir"] = "site/zh"
    zh_cfg["site_url"] = (site_url.rstrip("/") if site_url else "") + "/zh/"
    zh_cfg.setdefault("theme", {})["language"] = "zh"
    walk(zh_cfg.get("nav", []))
    zh_cfg.setdefault("extra", {})["alternate"] = alternates
    (ROOT / "mkdocs-zh.yml").write_text(
        yaml.dump(
            zh_cfg, Dumper=_Dumper, allow_unicode=True, default_flow_style=False, sort_keys=False
        ),
        encoding="utf-8",
    )

    print("Generated mkdocs-en.yml and mkdocs-zh.yml from mkdocs.yml")


if __name__ == "__main__":
    main()
