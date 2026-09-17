import os
import re
import traceback
from datetime import datetime

from biz.entity.review_entity import MergeRequestReviewEntity, PushReviewEntity
from biz.event.event_manager import _build_branch_rejection_message, event_manager
from biz.context.window import build_review_context
from biz.diff.filter import DiffFilterResult, filter_diffs_with_stats
from biz.diff.parser import parse_changes
from biz.platforms.gitlab.webhook_handler import (
    MergeRequestHandler,
    PushHandler,
)
from biz.platforms.github.webhook_handler import (
    PullRequestHandler as GithubPullRequestHandler,
    PushHandler as GithubPushHandler,
)
from biz.model.diff import Diff
from biz.model.review_comment import ReviewResult
from biz.model.review_context import ReviewContext
from biz.service.review_service import ReviewService
from biz.utils.code_reviewer import CodeReviewer
from biz.utils.im import notifier
from biz.utils.log import logger
from biz.utils.review_renderer import render_review_markdown


def _safe_commit_message(commit: dict) -> str:
    return (commit.get("message") or "").strip()


def _build_commits_text(commits: list[dict]) -> str:
    return ";".join(_safe_commit_message(commit) for commit in commits)


def _count_change_stats(changes: list[Diff]) -> tuple[int, int]:
    additions = 0
    deletions = 0
    for item in changes:
        additions += item.additions
        deletions += item.deletions
    return additions, deletions


def _filter_changes_with_stats(changes: list[dict], source: str) -> DiffFilterResult:
    return filter_diffs_with_stats(parse_changes(changes, source=source))


def _gitlab_project_context(webhook_data: dict) -> dict:
    return webhook_data.get("project", {}) or {}


def _github_project_context(webhook_data: dict) -> dict:
    repository = webhook_data.get("repository", {}) or {}
    return {
        "name": repository.get("name"),
        "path": repository.get("name"),
        "full_name": repository.get("full_name"),
        "html_url": repository.get("html_url"),
    }


def _build_context(
    handler, changes: list[Diff], ref: str | None
) -> ReviewContext | None:
    if not ref or not hasattr(handler, "get_file_content"):
        return None
    try:
        return build_review_context(changes, ref, handler.get_file_content)
    except Exception as e:
        logger.warning(
            "Failed to build review context, falling back to diff-only review: %s", e
        )
        return None


def _review_changes(
    changes: list[Diff],
    commits: list[dict],
    project_context: dict | None = None,
    review_context: ReviewContext | None = None,
    input_warnings: list[str] | None = None,
) -> tuple[str, int | None, ReviewResult]:
    review_result = CodeReviewer(project_context).review_diffs(
        changes,
        _build_commits_text(commits),
        review_context,
        input_warnings=input_warnings,
    )
    return render_review_markdown(review_result), review_result.score, review_result


BRANCH_GUIDE_URL = "https://developer-docs.jrtzcloud.cn/rd-quality/git/git-branch.html"
BRANCH_NAME_PATTERN = re.compile(
    r"^(?:main|dev|(?:feat|fix|hotfix|dev|main|delay)/[^/\s]+(?:/[^/\s]+)*)$"
)


def _merge_route_error(source_branch: str, target_branch: str) -> str | None:
    if not BRANCH_NAME_PATTERN.fullmatch(source_branch):
        return f"源分支名不符合规范：{source_branch}"
    if not BRANCH_NAME_PATTERN.fullmatch(target_branch):
        return f"目标分支名不符合规范：{target_branch}"

    valid_route = (
        (source_branch.startswith(("feat/", "fix/")) and target_branch == "dev")
        or (source_branch.startswith("hotfix/") and target_branch == "main")
        or (source_branch == "dev" and target_branch == "main")
    )
    if not valid_route:
        return (
            f"不允许的合并方向：{source_branch} → {target_branch}；"
            "允许 feat/*、fix/* → dev，hotfix/* → main，dev → main"
        )
    return None


def _should_auto_merge(review_result: ReviewResult) -> bool:
    if os.environ.get("GITLAB_AUTO_MERGE_ENABLED", "0") != "1":
        return False
    try:
        min_score = int(os.environ.get("GITLAB_AUTO_MERGE_MIN_SCORE", "90"))
    except ValueError:
        logger.error("GITLAB_AUTO_MERGE_MIN_SCORE must be an integer.")
        return False
    allowed_risks = {
        value.strip().lower()
        for value in os.environ.get(
            "GITLAB_AUTO_MERGE_ALLOWED_RISK_LEVELS", "low,低"
        ).split(",")
        if value.strip()
    }
    allowed_advices = {
        value.strip().lower()
        for value in os.environ.get(
            "GITLAB_AUTO_MERGE_ALLOWED_ADVICES", "approved,建议合并"
        ).split(",")
        if value.strip()
    }
    return (
        review_result.score is not None
        and review_result.score >= min_score
        and review_result.risk_level.strip().lower() in allowed_risks
        and review_result.merge_advice.strip().lower() in allowed_advices
    )


def handle_push_event(
    webhook_data: dict, gitlab_token: str, gitlab_url: str, gitlab_url_slug: str
):
    push_review_enabled = os.environ.get("PUSH_REVIEW_ENABLED", "0") == "1"
    try:
        handler = PushHandler(webhook_data, gitlab_token, gitlab_url)
        logger.info("Push Hook event received")
        commits = handler.get_push_commits()
        if not commits:
            logger.error("Failed to get commits")
            return
        if not push_review_enabled:
            logger.info("Push review is disabled, skipping review event.")
            return

        review_result = None
        score = 0
        additions = 0
        deletions = 0
        if push_review_enabled:
            changes = handler.get_push_changes()
            logger.info("changes: %s", changes)
            filter_result = _filter_changes_with_stats(changes, source="gitlab")
            changes = filter_result.diffs
            if not changes:
                logger.info(
                    "No code changes detected in supported file types."
                )
            review_result = "No changes in tracked files"

            if len(changes) > 0:
                review_context = _build_context(
                    handler, changes, webhook_data.get("after")
                )
                review_result, score, _ = _review_changes(
                    changes,
                    commits,
                    _gitlab_project_context(webhook_data),
                    review_context,
                    filter_result.to_warnings(),
                )
                additions, deletions = _count_change_stats(changes)
            # Post review result as GitLab note
            handler.add_push_notes(f"Auto Review Result: \n{review_result}")

        event_manager["push_reviewed"].send(
            PushReviewEntity(
                project_name=webhook_data["project"]["name"],
                author=webhook_data["user_username"],
                branch=webhook_data.get("ref", "").replace("refs/heads/", ""),
                updated_at=int(datetime.now().timestamp()),
                commits=commits,
                score=score,
                review_result=review_result,
                url_slug=gitlab_url_slug,
                webhook_data=webhook_data,
                additions=additions,
                deletions=deletions,
            )
        )

    except Exception as e:
        error_message = f"Unexpected error: {str(e)}\n{traceback.format_exc()}"
        notifier.send_notification(content=error_message)
        logger.error("Unexpected error: %s", error_message)


def handle_merge_request_event(
    webhook_data: dict, gitlab_token: str, gitlab_url: str, gitlab_url_slug: str
):
    """
    Handle GitLab Merge Request Hook event
    """
    merge_review_only_protected_branches = (
        os.environ.get("MERGE_REVIEW_ONLY_PROTECTED_BRANCHES_ENABLED", "0") == "1"
    )
    try:
        handler = MergeRequestHandler(webhook_data, gitlab_token, gitlab_url)
        logger.info("Merge Request Hook event received")

        object_attributes = webhook_data.get("object_attributes", {})
        is_draft = object_attributes.get("draft") or object_attributes.get(
            "work_in_progress"
        )
        if is_draft:
            msg = (
                f"[Notice] MR is draft, AI review skipped.\n"
                f"Project: {webhook_data['project']['name']}\n"
                f"Author: {webhook_data['user']['username']}\n"
                f"Source Branch: {object_attributes.get('source_branch')}\n"
                f"Target Branch: {object_attributes.get('target_branch')}"
            )
            notifier.send_notification(content=msg)
            logger.info("MR is draft, sending notification only, skipping AI review.")
            return

        if handler.action not in ["open", "update"]:
            logger.info(f"Merge Request Hook event, action={handler.action}, ignored.")
            return

        project_name = webhook_data["project"]["name"]
        author = webhook_data["user"]["username"]
        source_branch = object_attributes.get("source_branch", "")
        target_branch = object_attributes.get("target_branch", "")
        route_error = _merge_route_error(source_branch, target_branch)
        if route_error:
            note = (
                "Auto Review Result: \n## 合并请求已驳回\n"
                f"{route_error}\n\n分支规范：{BRANCH_GUIDE_URL}"
            )
            handler.add_merge_request_notes(note)
            notifier.send_notification(
                content=_build_branch_rejection_message(
                    project_name,
                    author,
                    source_branch,
                    target_branch,
                    object_attributes.get("url", ""),
                    route_error,
                    BRANCH_GUIDE_URL,
                ),
                msg_type="text",
                project_name=project_name,
                url_slug=gitlab_url_slug,
                webhook_data=webhook_data,
            )
            logger.info("Merge Request rejected by branch policy: %s", route_error)
            return

        if (
            merge_review_only_protected_branches
            and not handler.target_branch_protected()
        ):
            logger.info(
                "Merge Request target branch not match protected branches, ignored."
            )
            return

        last_commit_id = object_attributes.get("last_commit", {}).get("id", "")
        if last_commit_id:
            if ReviewService.check_mr_last_commit_id_exists(
                project_name, source_branch, target_branch, last_commit_id
            ):
                logger.info(
                    f"Merge Request with last_commit_id {last_commit_id} already exists, "
                    f"skipping review for {project_name}."
                )
                return

        changes = handler.get_merge_request_changes()
        logger.info("changes: %s", changes)
        filter_result = _filter_changes_with_stats(changes, source="gitlab")
        changes = filter_result.diffs
        if not changes:
            logger.info(
                "No code changes detected in supported file types."
            )
            return
        additions, deletions = _count_change_stats(changes)

        commits = handler.get_merge_request_commits()
        if not commits:
            logger.error("Failed to get commits")
            return

        review_context = _build_context(handler, changes, last_commit_id)
        review_result, score, structured_review = _review_changes(
            changes,
            commits,
            _gitlab_project_context(webhook_data),
            review_context,
            filter_result.to_warnings(),
        )

        handler.add_merge_request_notes(f"Auto Review Result: \n{review_result}")

        auto_merged = False
        if last_commit_id and _should_auto_merge(structured_review):
            try:
                handler.merge_merge_request(last_commit_id)
                auto_merged = True
            except Exception as e:
                logger.error("GitLab auto-merge failed: %s", e)

        event_manager["merge_request_reviewed"].send(
            MergeRequestReviewEntity(
                project_name=webhook_data["project"]["name"],
                author=webhook_data["user"]["username"],
                source_branch=webhook_data["object_attributes"]["source_branch"],
                target_branch=webhook_data["object_attributes"]["target_branch"],
                updated_at=int(datetime.now().timestamp()),
                commits=commits,
                score=score,
                url=webhook_data["object_attributes"]["url"],
                review_result=review_result,
                url_slug=gitlab_url_slug,
                webhook_data=webhook_data,
                additions=additions,
                deletions=deletions,
                last_commit_id=last_commit_id,
                auto_merged=auto_merged,
                review_summary=structured_review.summary,
            )
        )

    except Exception as e:
        error_message = (
            f"AI Code Review unexpected error: {str(e)}\n{traceback.format_exc()}"
        )
        notifier.send_notification(content=error_message)
        logger.error("Unexpected error: %s", error_message)


def handle_github_push_event(
    webhook_data: dict, github_token: str, github_url: str, github_url_slug: str
):
    push_review_enabled = os.environ.get("PUSH_REVIEW_ENABLED", "0") == "1"
    try:
        handler = GithubPushHandler(webhook_data, github_token, github_url)
        logger.info("GitHub Push event received")
        commits = handler.get_push_commits()
        if not commits:
            logger.error("Failed to get commits")
            return
        if not push_review_enabled:
            logger.info("GitHub push review is disabled, skipping review event.")
            return

        review_result = None
        score = 0
        additions = 0
        deletions = 0
        if push_review_enabled:
            changes = handler.get_push_changes()
            logger.info("changes: %s", changes)
            filter_result = _filter_changes_with_stats(changes, source="github")
            changes = filter_result.diffs
            if not changes:
                logger.info(
                    "No code changes detected in supported file types."
                )
            review_result = "No changes in tracked files"

            if len(changes) > 0:
                review_context = _build_context(
                    handler, changes, webhook_data.get("after")
                )
                review_result, score, _ = _review_changes(
                    changes,
                    commits,
                    _github_project_context(webhook_data),
                    review_context,
                    filter_result.to_warnings(),
                )
                additions, deletions = _count_change_stats(changes)
            handler.add_push_notes(f"Auto Review Result: \n{review_result}")

        event_manager["push_reviewed"].send(
            PushReviewEntity(
                project_name=webhook_data["repository"]["name"],
                author=webhook_data["sender"]["login"],
                branch=webhook_data["ref"].replace("refs/heads/", ""),
                updated_at=int(datetime.now().timestamp()),
                commits=commits,
                score=score,
                review_result=review_result,
                url_slug=github_url_slug,
                webhook_data=webhook_data,
                additions=additions,
                deletions=deletions,
            )
        )

    except Exception as e:
        error_message = f"Unexpected error: {str(e)}\n{traceback.format_exc()}"
        notifier.send_notification(content=error_message)
        logger.error("Unexpected error: %s", error_message)


def handle_github_pull_request_event(
    webhook_data: dict, github_token: str, github_url: str, github_url_slug: str
):
    """
    Handle GitHub Pull Request event
    """
    merge_review_only_protected_branches = (
        os.environ.get("MERGE_REVIEW_ONLY_PROTECTED_BRANCHES_ENABLED", "0") == "1"
    )
    try:
        handler = GithubPullRequestHandler(webhook_data, github_token, github_url)
        logger.info("GitHub Pull Request event received")
        if (
            merge_review_only_protected_branches
            and not handler.target_branch_protected()
        ):
            logger.info(
                "Merge Request target branch not match protected branches, ignored."
            )
            return

        if handler.action not in ["opened", "synchronize"]:
            logger.info(f"Pull Request Hook event, action={handler.action}, ignored.")
            return

        github_last_commit_id = webhook_data["pull_request"]["head"]["sha"]
        if github_last_commit_id:
            project_name = webhook_data["repository"]["name"]
            source_branch = webhook_data["pull_request"]["head"]["ref"]
            target_branch = webhook_data["pull_request"]["base"]["ref"]

            if ReviewService.check_mr_last_commit_id_exists(
                project_name, source_branch, target_branch, github_last_commit_id
            ):
                logger.info(
                    f"Pull Request with last_commit_id {github_last_commit_id} already exists, "
                    f"skipping review for {project_name}."
                )
                return

        changes = handler.get_pull_request_changes()
        logger.info("changes: %s", changes)
        filter_result = _filter_changes_with_stats(changes, source="github")
        changes = filter_result.diffs
        if not changes:
            logger.info(
                "No code changes detected in supported file types."
            )
            return
        additions, deletions = _count_change_stats(changes)

        commits = handler.get_pull_request_commits()
        if not commits:
            logger.error("Failed to get commits")
            return

        review_context = _build_context(handler, changes, github_last_commit_id)
        review_result, score, structured_review = _review_changes(
            changes,
            commits,
            _github_project_context(webhook_data),
            review_context,
            filter_result.to_warnings(),
        )

        handler.add_pull_request_notes(f"Auto Review Result: \n{review_result}")

        event_manager["merge_request_reviewed"].send(
            MergeRequestReviewEntity(
                project_name=webhook_data["repository"]["name"],
                author=webhook_data["pull_request"]["user"]["login"],
                source_branch=webhook_data["pull_request"]["head"]["ref"],
                target_branch=webhook_data["pull_request"]["base"]["ref"],
                updated_at=int(datetime.now().timestamp()),
                commits=commits,
                score=score,
                url=webhook_data["pull_request"]["html_url"],
                review_result=review_result,
                url_slug=github_url_slug,
                webhook_data=webhook_data,
                additions=additions,
                deletions=deletions,
                last_commit_id=github_last_commit_id,
                review_summary=structured_review.summary,
            )
        )

    except Exception as e:
        error_message = f"Unexpected error: {str(e)}\n{traceback.format_exc()}"
        notifier.send_notification(content=error_message)
        logger.error("Unexpected error: %s", error_message)
