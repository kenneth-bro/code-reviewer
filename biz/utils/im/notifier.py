import os
import re
from urllib.parse import quote

import requests

from biz.utils.im.dingtalk import DingTalkNotifier
from biz.utils.im.feishu import FeishuNotifier
from biz.utils.im.webhook import ExtraWebhookNotifier
from biz.utils.im.wecom import WeComNotifier
from biz.utils.log import logger

HTTP_TIMEOUT_SECONDS = float(os.getenv("HTTP_TIMEOUT_SECONDS", "10"))


def _gitlab_author_id(webhook_data: dict | None):
    if not webhook_data or not webhook_data.get("object_kind"):
        return None
    attributes = webhook_data.get("object_attributes") or {}
    user = webhook_data.get("user") or {}
    return attributes.get("author_id") or user.get("id") or webhook_data.get("user_id")


def _gitlab_author_mobile(webhook_data: dict | None) -> str | None:
    user_id = _gitlab_author_id(webhook_data)
    gitlab_url = os.getenv("GITLAB_URL", "").rstrip("/")
    gitlab_token = os.getenv("GITLAB_ACCESS_TOKEN", "")
    attribute_key = os.getenv("GITLAB_MOBILE_ATTRIBUTE_KEY", "手机号码")
    if not user_id or not gitlab_url or not gitlab_token or not attribute_key:
        return None

    url = (
        f"{gitlab_url}/api/v4/users/{user_id}/custom_attributes/"
        f"{quote(attribute_key, safe='')}"
    )
    try:
        response = requests.get(
            url,
            headers={"Private-Token": gitlab_token},
            verify=False,
            timeout=HTTP_TIMEOUT_SECONDS,
        )
        if response.status_code == 404:
            return None
        if response.status_code != 200:
            logger.warning(
                "Failed to read GitLab mobile custom attribute: user_id=%s status=%s",
                user_id,
                response.status_code,
            )
            return None
        mobile = re.sub(r"\D", "", str(response.json().get("value", "")))
        if 7 <= len(mobile) <= 15:
            return mobile
        logger.warning("Invalid GitLab mobile custom attribute: user_id=%s", user_id)
    except requests.RequestException as exc:
        logger.warning(
            "Failed to read GitLab mobile custom attribute: user_id=%s error=%s",
            user_id,
            exc,
        )
    return None


def send_notification(
    content,
    msg_type="markdown",
    title="Notification",
    is_at_all=False,
    project_name=None,
    url_slug="",
    webhook_data=None,
):
    """Send a review notification to configured channels."""
    dingtalk_notifier = DingTalkNotifier()
    dingtalk_notifier.send_message(
        content=content,
        msg_type=msg_type,
        title=title,
        is_at_all=is_at_all,
        project_name=project_name,
        url_slug=url_slug,
    )

    wecom_notifier = WeComNotifier()
    mobile = None
    if (
        wecom_notifier.enabled
        and os.getenv("WECOM_MENTION_AUTHOR_ENABLED", "0") == "1"
    ):
        mobile = _gitlab_author_mobile(webhook_data)
    wecom_notifier.send_message(
        content=content,
        msg_type=msg_type,
        title=title,
        is_at_all=is_at_all,
        project_name=project_name,
        url_slug=url_slug,
        mentioned_mobiles=[mobile] if mobile and msg_type == "text" else None,
    )
    if mobile and msg_type != "text":
        user = (webhook_data or {}).get("user") or {}
        username = (
            user.get("username")
            if user.get("id") == _gitlab_author_id(webhook_data)
            else None
        ) or "MR 作者"
        wecom_notifier.send_message(
            content=f"请 {username} 关注以上代码评审结果。",
            msg_type="text",
            project_name=project_name,
            url_slug=url_slug,
            mentioned_mobiles=[mobile],
        )

    feishu_notifier = FeishuNotifier()
    feishu_notifier.send_message(
        content=content,
        msg_type=msg_type,
        title=title,
        is_at_all=is_at_all,
        project_name=project_name,
        url_slug=url_slug,
    )

    extra_webhook_notifier = ExtraWebhookNotifier()
    system_data = {
        "content": content,
        "msg_type": msg_type,
        "title": title,
        "is_at_all": is_at_all,
        "project_name": project_name,
        "url_slug": url_slug,
    }
    extra_webhook_notifier.send_message(
        system_data=system_data,
        webhook_data=webhook_data or {},
    )
