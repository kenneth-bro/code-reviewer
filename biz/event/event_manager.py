from datetime import datetime

from blinker import Signal

from biz.entity.review_entity import MergeRequestReviewEntity, PushReviewEntity
from biz.service.review_service import ReviewService
from biz.utils.im import notifier
from biz.utils.log import logger

# Define global event manager (event signals)
event_manager = {
    "merge_request_reviewed": Signal(),
    "push_reviewed": Signal(),
}

WECOM_TEXT_MAX_BYTES = 2048


def _format_time(timestamp: int) -> str:
    return datetime.fromtimestamp(timestamp).astimezone().strftime("%Y-%m-%d %H:%M:%S")


def _build_merge_request_message(entity: MergeRequestReviewEntity) -> str:
    attributes = (entity.webhook_data or {}).get("object_attributes") or {}
    user = (entity.webhook_data or {}).get("user") or {}
    title = attributes.get("title") or entity.project_name
    author = user.get("name") or entity.author
    status = "✅ 已合并" if entity.auto_merged else "⛔ 已驳回"
    summary = entity.review_summary or "评审未通过，请查看 PR 详情。"
    lines = [
        f"PR: {title}  {entity.url}",
        f"合并方向： {entity.source_branch} -> {entity.target_branch}",
        f"创建人:  @{author}",
        f"当前状态: {status}",
        "评审意见摘要（详情查看PR）：",
        f"1、{summary}",
    ]
    return _limit_notification_message("\n".join(lines))


def _build_branch_rejection_message(
    project_name: str,
    author: str,
    source_branch: str,
    target_branch: str,
    url: str,
    reason: str,
    guide_url: str,
) -> str:
    return _limit_notification_message("\n".join(
        [
            f"PR: {project_name}  {url}",
            f"合并方向： {source_branch} -> {target_branch}",
            f"创建人:  @{author}",
            "当前状态: ⛔ 已驳回",
            "评审意见摘要（详情查看PR）：",
            f"1、{reason}",
            f"2、分支规范：{guide_url}",
        ]
    ))


def _limit_notification_message(content: str) -> str:
    suffix = "\n（摘要已截断，详情请查看 PR）"
    if len(content.encode("utf-8")) <= WECOM_TEXT_MAX_BYTES:
        return content

    budget = WECOM_TEXT_MAX_BYTES - len(suffix.encode("utf-8"))
    truncated = content.encode("utf-8")[:budget].decode("utf-8", errors="ignore")
    return truncated + suffix


def _build_push_message(entity: PushReviewEntity) -> str:
    lines = [
        f"> 分支：`{entity.branch}`　代码变更：新增 {entity.additions} 行，删除 {entity.deletions} 行",
        "",
        "### 提交记录",
    ]
    for commit in entity.commits:
        message = (commit.get("message") or "").strip()
        author = commit.get("author", "未知提交人")
        timestamp = commit.get("timestamp", "")
        url = commit.get("url", "#")
        lines.extend(
            [
                f"- **{message}**",
                f"  - 提交人：{author}",
                f"  - 时间：{timestamp}",
                f"  - [查看提交]({url})",
            ]
        )
    if entity.review_result:
        lines.extend(["", entity.review_result])
    return "\n".join(lines)


# Define event handler
def on_merge_request_reviewed(mr_review_entity: MergeRequestReviewEntity):
    notifier.send_notification(
        content=_build_merge_request_message(mr_review_entity),
        msg_type="text",
        project_name=mr_review_entity.project_name,
        url_slug=mr_review_entity.url_slug,
        webhook_data=mr_review_entity.webhook_data,
    )

    if not ReviewService().insert_mr_review_log(mr_review_entity):
        logger.error(
            "Failed to persist merge request review log: project=%s source=%s target=%s",
            mr_review_entity.project_name,
            mr_review_entity.source_branch,
            mr_review_entity.target_branch,
        )


def on_push_reviewed(entity: PushReviewEntity):
    notifier.send_notification(
        content=_build_push_message(entity),
        msg_type="markdown",
        title=f"🚀 {entity.project_name}｜推送评审",
        project_name=entity.project_name,
        url_slug=entity.url_slug,
        webhook_data=entity.webhook_data,
    )

    if not ReviewService().insert_push_review_log(entity):
        logger.error(
            "Failed to persist push review log: project=%s branch=%s",
            entity.project_name,
            entity.branch,
        )


# Connect handlers to event signals
event_manager["merge_request_reviewed"].connect(on_merge_request_reviewed)
event_manager["push_reviewed"].connect(on_push_reviewed)
