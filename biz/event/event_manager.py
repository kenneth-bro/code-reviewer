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


def _format_time(timestamp: int) -> str:
    return datetime.fromtimestamp(timestamp).astimezone().strftime("%Y-%m-%d %H:%M:%S")


def _build_merge_request_message(entity: MergeRequestReviewEntity) -> str:
    if entity.auto_merged:
        return f"{entity.project_name}：合并请求已自动合并。\n{entity.url}"
    return (
        f"{entity.project_name}：合并请求未自动合并，请查看修改意见：\n"
        f"{entity.url}"
    )


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
