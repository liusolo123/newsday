from __future__ import annotations

import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
import json
from pathlib import Path

sys.modules.setdefault("requests", Mock())

import llm_polish


class LlmPolishTests(unittest.TestCase):
    def test_check_output_requires_chinese_and_source_numbers(self) -> None:
        material = "该开源项目已获得 2,273 颗星标，最新版本为 3.8。"
        valid = "该开源项目已获得2273颗星标，最新版本为3.8，并面向开发者提供工具支持。"

        self.assertIsNone(llm_polish.check_output(valid, material))
        self.assertEqual(
            llm_polish.check_output("This project has 2273 stars and is version 3.8 today.", material),
            "中文不足",
        )
        self.assertEqual(
            llm_polish.check_output("该项目拥有999颗星标，并提供面向开发者的工具支持和完整使用说明。", material),
            "新增或变更数字",
        )

    @patch("llm_polish.call_deepseek")
    def test_invalid_flash_output_is_repaired_by_pro(self, mock_call: Mock) -> None:
        mock_call.side_effect = [
            ("This is an English summary without Chinese output for the reader.", {"model": "deepseek-v4-flash"}),
            ("该项目发布了一项面向开发者的开源工具，材料显示其功能集中于自动化代码处理。", {"model": "deepseek-v4-pro"}),
        ]

        result = llm_polish.polish_item(
            title="Example Project",
            material="项目发布了一项面向开发者的开源工具，功能集中于自动化代码处理。",
            source="github_search",
            api_key="test-key",
            primary_model="deepseek-v4-flash",
            repair_model="deepseek-v4-pro",
        )

        self.assertEqual(result.status, "pro")
        self.assertGreaterEqual(llm_polish.count_cn(result.text), 10)
        self.assertEqual(mock_call.call_args_list[0].kwargs["model"], "deepseek-v4-flash")
        self.assertEqual(mock_call.call_args_list[1].kwargs["model"], "deepseek-v4-pro")

    @patch("llm_polish.call_deepseek", side_effect=RuntimeError("service unavailable"))
    def test_failures_use_chinese_safe_fallback(self, mock_call: Mock) -> None:
        result = llm_polish.polish_item(
            title="Example Project",
            material="",
            source="github_search",
            api_key="test-key",
            primary_model="deepseek-v4-flash",
            repair_model="deepseek-v4-pro",
        )

        self.assertEqual(result.status, "fallback")
        self.assertGreaterEqual(llm_polish.count_cn(result.text), 10)
        self.assertEqual(mock_call.call_count, 3)

    def test_missing_key_uses_chinese_safe_fallback_without_request(self) -> None:
        with patch("llm_polish.call_deepseek") as mock_call:
            result = llm_polish.polish_item(
                title="Example Project",
                material="项目材料。",
                source="github_search",
                api_key="",
                primary_model="deepseek-v4-flash",
                repair_model="deepseek-v4-pro",
            )

        self.assertEqual(result.status, "fallback")
        self.assertGreaterEqual(llm_polish.count_cn(result.text), 10)
        mock_call.assert_not_called()

    @patch("llm_polish.requests.post")
    def test_request_uses_v4_and_disables_thinking(self, mock_post: Mock) -> None:
        response = Mock()
        response.json.return_value = {
            "choices": [{"message": {"content": "该项目提供面向开发者的开源工具，相关功能已经公开。"}}]
        }
        mock_post.return_value = response

        text, usage = llm_polish.call_deepseek(
            title="Example Project",
            material="项目提供开源工具。",
            source="github_search",
            api_key="test-key",
            model="deepseek-v4-flash",
            system_prompt="test",
        )

        self.assertEqual(text, "该项目提供面向开发者的开源工具，相关功能已经公开。")
        self.assertEqual(usage["model"], "deepseek-v4-flash")
        payload = mock_post.call_args.kwargs["json"]
        self.assertEqual(payload["model"], "deepseek-v4-flash")
        self.assertEqual(payload["thinking"], {"type": "disabled"})
        self.assertEqual(payload["temperature"], 0.2)

    def test_record_api_usage_accumulates_models(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.object(llm_polish, "ROOT", Path(directory)), patch.object(llm_polish, "TODAY", "2026-09-03"):
            path = llm_polish.record_api_usage([
                {"model": "deepseek-v4-flash", "prompt_tokens": 4, "completion_tokens": 5, "reasoning_tokens": 0, "total_tokens": 9},
                {"model": "deepseek-v4-flash", "prompt_tokens": 6, "completion_tokens": 7, "reasoning_tokens": 0, "total_tokens": 13},
            ])
            data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(data["models"]["deepseek-v4-flash"]["calls"], 2)
        self.assertEqual(data["models"]["deepseek-v4-flash"]["total_tokens"], 22)


if __name__ == "__main__":
    unittest.main()
