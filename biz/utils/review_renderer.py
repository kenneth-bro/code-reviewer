from biz.model.review_comment import ReviewComment, ReviewResult


SEVERITY_LABELS = {
    "high": "高",
    "medium": "中",
    "low": "低",
    "info": "提示",
}
CATEGORY_LABELS = {
    "correctness": "正确性",
    "compatibility": "兼容性",
    "security": "安全",
    "performance": "性能",
    "maintainability": "可维护性",
    "test": "测试",
}


def _format_score(score: int | None) -> str:
    return f"{score}" if score is not None else "N/A"


def _format_comment(comment: ReviewComment, index: int) -> str:
    location = comment.path
    if comment.line_resolved and comment.start_line and comment.end_line:
        if comment.start_line == comment.end_line:
            location = f"{location}:{comment.start_line}"
        else:
            location = f"{location}:{comment.start_line}-{comment.end_line}"
    else:
        location = f"{location}:未定位"

    severity = SEVERITY_LABELS.get(comment.severity, comment.severity)
    category = CATEGORY_LABELS.get(
        comment.category, comment.category or "未分类"
    )
    parts = [
        f"{index}. **{severity}** `{location}`",
        f"   - 类型：{category}",
        f"   - 问题：{comment.content}",
    ]
    if not comment.line_resolved and comment.resolve_reason:
        parts.append(f"   - 定位说明：{comment.resolve_reason}")
    return "\n".join(parts)


def _looks_like_structured_output(text: str) -> bool:
    stripped = (text or "").lstrip()
    return stripped.startswith("{") or stripped.startswith("```json")


def _render_parse_error(result: ReviewResult) -> str:
    if result.raw_text and not _looks_like_structured_output(result.raw_text):
        return result.raw_text
    return "\n".join(
        [
            "## 评审结论",
            "- 风险等级：低",
            "- 合并建议：建议合并",
            "- 综合评分：N/A",
            "",
            "模型返回的结构化结果无法解析，已转换为标准格式；原始内容未直接发布，避免影响消息展示。",
            "",
            "## 主要问题",
            "无法解析结构化问题列表，请检查服务日志中的原始模型响应。",
        ]
    )


def render_review_markdown(result: ReviewResult) -> str:
    if result.parse_error:
        return _render_parse_error(result)

    lines = [
        "## 评审结论",
        f"- 风险等级：{result.risk_level or '低'}",
        f"- 合并建议：{result.merge_advice or '建议合并'}",
        f"- 综合评分：{_format_score(result.score)}",
        "",
        result.summary or "未发现明确问题。",
        "",
    ]
    if result.input_warnings:
        lines.append("## 输入完整性")
        lines.extend(f"- {warning}" for warning in result.input_warnings)
        lines.append("")

    lines.append("## 主要问题")
    if result.comments:
        for index, comment in enumerate(result.comments, start=1):
            lines.append(_format_comment(comment, index))
    else:
        lines.append("未发现明确问题。")

    return "\n".join(lines).strip()
