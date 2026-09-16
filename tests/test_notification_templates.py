import unittest

from biz.entity.review_entity import MergeRequestReviewEntity, PushReviewEntity
from biz.event.event_manager import _build_merge_request_message, _build_push_message


class NotificationTemplateTest(unittest.TestCase):
    def test_merge_request_template_reports_merge_outcome_and_link(self):
        values = dict(
            project_name="示例项目",
            author="张三",
            source_branch="feature/demo",
            target_branch="main",
            updated_at=1700000000,
            commits=[{"message": "新增功能"}],
            score=95,
            url="https://gitlab.example.com/mr/1",
            review_result="## 评审结论\n- 综合评分：95",
            url_slug="demo",
            webhook_data={},
            additions=12,
            deletions=3,
            last_commit_id="abc123",
        )

        merged = _build_merge_request_message(
            MergeRequestReviewEntity(**values, auto_merged=True)
        )
        unmerged = _build_merge_request_message(
            MergeRequestReviewEntity(**values, auto_merged=False)
        )

        self.assertEqual(
            merged,
            "示例项目：合并请求已自动合并。\nhttps://gitlab.example.com/mr/1",
        )
        self.assertEqual(
            unmerged,
            "示例项目：合并请求未自动合并，请查看修改意见：\n"
            "https://gitlab.example.com/mr/1",
        )

    def test_push_template_is_concise_chinese_and_complete(self):
        entity = PushReviewEntity(
            project_name="示例项目",
            author="张三",
            branch="develop",
            updated_at=1700000000,
            commits=[
                {
                    "message": "修复问题",
                    "author": "张三",
                    "timestamp": "2026-09-16T10:00:00+08:00",
                    "url": "https://gitlab.example.com/commit/abc",
                }
            ],
            score=88,
            review_result="## 评审结论\n- 综合评分：88",
            url_slug="demo",
            webhook_data={},
            additions=5,
            deletions=1,
        )

        message = _build_push_message(entity)

        for expected in (
            "分支：`develop`",
            "新增 5 行，删除 1 行",
            "### 提交记录",
            "修复问题",
            "提交人：张三",
            "https://gitlab.example.com/commit/abc",
            "综合评分：88",
        ):
            self.assertIn(expected, message)
        self.assertNotIn("Push Event", message)


if __name__ == "__main__":
    unittest.main()
