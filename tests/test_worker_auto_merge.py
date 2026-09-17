import os
import unittest
from unittest.mock import Mock, patch

from biz.model.review_comment import ReviewResult
from biz.platforms.gitlab.webhook_handler import MergeRequestHandler
from biz.queue.worker import _merge_route_error, _should_auto_merge


class WorkerAutoMergeTest(unittest.TestCase):
    @patch.dict(
        os.environ,
        {
            "GITLAB_AUTO_MERGE_ENABLED": "1",
            "GITLAB_AUTO_MERGE_MIN_SCORE": "90",
            "GITLAB_AUTO_MERGE_ALLOWED_RISK_LEVELS": "low,低",
            "GITLAB_AUTO_MERGE_ALLOWED_ADVICES": "approved,建议合并",
        },
        clear=True,
    )
    def test_only_low_risk_approval_is_auto_merged(self):
        self.assertTrue(
            _should_auto_merge(
                ReviewResult(
                    summary="ok", score=96, risk_level="低", merge_advice="建议合并"
                )
            )
        )
        self.assertFalse(
            _should_auto_merge(
                ReviewResult(
                    summary="fix", score=82, risk_level="中", merge_advice="修复后合并"
                )
            )
        )

    def test_merge_routes_and_branch_names(self):
        for source, target in (
            ("feat/login", "dev"),
            ("fix/login", "dev"),
            ("hotfix/login", "main"),
            ("dev", "main"),
        ):
            self.assertIsNone(_merge_route_error(source, target))

        self.assertIn("分支名不符合规范", _merge_route_error("feature/login", "dev"))
        self.assertIn("分支名不符合规范", _merge_route_error("feat/", "dev"))
        self.assertIn("不允许的合并方向", _merge_route_error("feat/login", "main"))
        self.assertIn("不允许的合并方向", _merge_route_error("hotfix/login", "dev"))
        self.assertIn("不允许的合并方向", _merge_route_error("dev", "dev"))

    @patch("biz.platforms.gitlab.webhook_handler.requests.put")
    def test_merge_request_uses_reviewed_sha(self, put):
        put.return_value = Mock(status_code=200)
        handler = MergeRequestHandler(
            {
                "object_kind": "merge_request",
                "object_attributes": {
                    "iid": 7,
                    "target_project_id": 1047,
                    "action": "open",
                },
            },
            "token",
            "https://gitlab.example.com",
        )

        handler.merge_merge_request("abc123")

        self.assertEqual(put.call_args.kwargs["json"], {"sha": "abc123"})


if __name__ == "__main__":
    unittest.main()
