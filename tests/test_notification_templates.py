import unittest

from biz.entity.review_entity import MergeRequestReviewEntity, PushReviewEntity
from biz.event.event_manager import (
    _build_branch_rejection_message,
    _build_merge_request_message,
    _build_push_message,
)


class NotificationTemplateTest(unittest.TestCase):
    def test_merge_request_template_reports_merge_outcome_and_link(self):
        values = dict(
            project_name="示例项目",
            author="张三",
            source_branch="feat/demo",
            target_branch="dev",
            updated_at=1700000000,
            commits=[{"message": "新增功能"}],
            score=95,
            url="https://gitlab.example.com/mr/1",
            review_result="## 评审结论\n- 综合评分：95",
            url_slug="demo",
            webhook_data={
                "object_attributes": {"title": "新增功能"},
                "user": {"name": "李勤"},
            },
            additions=12,
            deletions=3,
            last_commit_id="abc123",
            review_summary="存在 SQL 注入风险，修复前不建议合并。",
        )

        merged = _build_merge_request_message(
            MergeRequestReviewEntity(**values, auto_merged=True)
        )
        unmerged = _build_merge_request_message(
            MergeRequestReviewEntity(**values, auto_merged=False)
        )

        self.assertEqual(
            merged,
            "PR: 新增功能  https://gitlab.example.com/mr/1\n"
            "合并方向： feat/demo -> dev\n"
            "创建人:  @李勤\n"
            "当前状态: ✅ 已合并\n"
            "评审意见摘要（详情查看PR）：\n"
            "1、存在 SQL 注入风险，修复前不建议合并。",
        )
        self.assertEqual(
            unmerged,
            "PR: 新增功能  https://gitlab.example.com/mr/1\n"
            "合并方向： feat/demo -> dev\n"
            "创建人:  @李勤\n"
            "当前状态: ⛔ 已驳回\n"
            "评审意见摘要（详情查看PR）：\n"
            "1、存在 SQL 注入风险，修复前不建议合并。",
        )

    def test_branch_rejection_template(self):
        message = _build_branch_rejection_message(
            "示例项目",
            "张三",
            "feature/demo",
            "dev",
            "https://gitlab.example.com/mr/2",
            "源分支名不符合规范：feature/demo",
            "https://developer-docs.jrtzcloud.cn/rd-quality/git/git-branch.html",
        )

        self.assertIn("PR: 示例项目  https://gitlab.example.com/mr/2", message)
        self.assertIn("合并方向： feature/demo -> dev", message)
        self.assertIn("当前状态: ⛔ 已驳回", message)
        self.assertIn("2、分支规范：https://developer-docs.jrtzcloud.cn", message)
        self.assertIn("创建人:  @张三", message)

    def test_merge_request_template_is_bounded(self):
        entity = MergeRequestReviewEntity(
            project_name="示例项目",
            author="张三",
            source_branch="feat/demo",
            target_branch="dev",
            updated_at=1700000000,
            commits=[],
            score=95,
            url="https://gitlab.example.com/mr/1",
            review_result="",
            url_slug="demo",
            webhook_data={},
            additions=0,
            deletions=0,
            last_commit_id="abc123",
            review_summary="问题" * 5000,
        )
        message = _build_merge_request_message(entity)
        self.assertLessEqual(len(message.encode("utf-8")), 2048)
        self.assertIn("详情请查看 PR", message)

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
