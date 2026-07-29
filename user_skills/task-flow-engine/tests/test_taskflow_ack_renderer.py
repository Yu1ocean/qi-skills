import unittest

from task_flow_engine.taskflow_ack_renderer import (
    DEFAULT_TASKFLOW_SHEET_URL,
    build_taskflow_ack_post,
    build_taskflow_ack_record,
    render_taskflow_ack_text,
)


class TestTaskflowAckRenderer(unittest.TestCase):
    def test_render_taskflow_ack_text_matches_minimal_spec(self):
        text = render_taskflow_ack_text(
            task_name="研究 chinamaxxing",
            owner="@李京达",
            status="✅ 已入库",
            sheet_url=DEFAULT_TASKFLOW_SHEET_URL,
        )
        self.assertEqual(
            text,
            "已录入任务台账：研究 chinamaxxing｜负责人：@李京达｜状态：✅ 已入库｜[打开任务库](https://bytedance.larkoffice.com/sheets/TnNYsLq9phIJwutJGwBl730ygjd?sheet=KmlJhs)",
        )
        self.assertEqual(text.count("https://bytedance.larkoffice.com/sheets/"), 1)
        self.assertNotIn("\n", text)

    def test_build_taskflow_ack_post_contains_single_link(self):
        payload = build_taskflow_ack_post(task_name="任务A", owner="@张三")
        row = payload["zh_cn"]["content"][0]
        self.assertEqual(len(row), 2)
        self.assertEqual(row[1]["href"], DEFAULT_TASKFLOW_SHEET_URL)

    def test_build_taskflow_ack_record_normalizes_missing_values(self):
        record = build_taskflow_ack_record(task_name="", owner="", status="", sheet_url="")
        self.assertEqual(record["task_name"], "未命名任务")
        self.assertEqual(record["owner"], "待补充")
        self.assertEqual(record["status"], "✅ 已入库")
        self.assertEqual(record["sheet_url"], DEFAULT_TASKFLOW_SHEET_URL)
        self.assertIn("[打开任务库](https://bytedance.larkoffice.com/sheets/", record["rendered_text"])


if __name__ == "__main__":
    unittest.main()
