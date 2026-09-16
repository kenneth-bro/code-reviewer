import os
import unittest
from unittest.mock import Mock, patch

from biz.utils.im import notifier
from biz.utils.im.wecom import WeComNotifier


class WeComMentionTest(unittest.TestCase):
    @patch("biz.utils.im.notifier.requests.get")
    @patch.dict(
        os.environ,
        {
            "GITLAB_URL": "https://gitlab.example.com",
            "GITLAB_ACCESS_TOKEN": "test-token",
            "GITLAB_MOBILE_ATTRIBUTE_KEY": "手机号码",
        },
        clear=True,
    )
    def test_reads_gitlab_mobile_custom_attribute(self, get):
        get.return_value = Mock(
            status_code=200,
            json=Mock(return_value={"key": "手机号码", "value": "185 0000 4960"}),
        )

        mobile = notifier._gitlab_author_mobile(
            {
                "object_kind": "merge_request",
                "user": {"id": 193},
                "object_attributes": {"author_id": 6},
            }
        )

        self.assertEqual(mobile, "18500004960")
        self.assertIn(
            "custom_attributes/%E6%89%8B%E6%9C%BA%E5%8F%B7%E7%A0%81",
            get.call_args.args[0],
        )

    @patch("biz.utils.im.notifier._gitlab_author_mobile", return_value="18500004960")
    @patch("biz.utils.im.notifier.ExtraWebhookNotifier")
    @patch("biz.utils.im.notifier.FeishuNotifier")
    @patch("biz.utils.im.notifier.WeComNotifier")
    @patch("biz.utils.im.notifier.DingTalkNotifier")
    @patch.dict(os.environ, {"WECOM_MENTION_AUTHOR_ENABLED": "1"}, clear=True)
    def test_sends_follow_up_text_mention_for_gitlab_author(
        self, dingtalk, wecom, feishu, extra, mobile_lookup
    ):
        wecom.return_value.enabled = True
        webhook_data = {
            "object_kind": "merge_request",
            "user": {"id": 6, "username": "liq"},
            "object_attributes": {"author_id": 6},
        }

        notifier.send_notification(
            content="评审报告",
            title="代码评审",
            project_name="Ai Reviewer",
            webhook_data=webhook_data,
        )

        self.assertEqual(wecom.return_value.send_message.call_count, 2)
        mention_call = wecom.return_value.send_message.call_args_list[1]
        self.assertEqual(mention_call.kwargs["msg_type"], "text")
        self.assertEqual(mention_call.kwargs["mentioned_mobiles"], ["18500004960"])
        self.assertIn("liq", mention_call.kwargs["content"])
        mobile_lookup.assert_called_once_with(webhook_data)

    def test_wecom_text_payload_contains_mobile_mentions(self):
        message = WeComNotifier()._build_text_message(
            "请关注评审结果", False, ["18500004960"]
        )

        self.assertEqual(
            message["text"]["mentioned_mobile_list"], ["18500004960"]
        )


if __name__ == "__main__":
    unittest.main()
