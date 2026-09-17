"""調査日固定と、既存セッションの復元・開示範囲の回帰テスト。

DB・Google Drive・LLMには接続しない。
"""

import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd

from modelRole import PatientRoleProvider


class InterviewDateTest(unittest.TestCase):
    def setUp(self):
        # 初期化時のGoogle認証を避け、日付処理に必要な患者データのみ与える。
        self.provider = PatientRoleProvider.__new__(PatientRoleProvider)

    def test_always_uses_last_day_without_time_suffix(self):
        for _ in range(20):
            date, suffix = self.provider._determine_interview_date("2022-04-20")
            self.assertEqual(date, datetime(2022, 4, 22))
            self.assertEqual(suffix, "")

    def test_calendar_boundaries(self):
        cases = [
            ("2022-04-30", datetime(2022, 5, 2)),
            ("2022-12-31", datetime(2023, 1, 2)),
            ("2024-02-28", datetime(2024, 3, 1)),
            ("2023-02-28", datetime(2023, 3, 2)),
            (pd.Timestamp("2022-04-20"), datetime(2022, 4, 22)),
        ]
        for value, expected in cases:
            with self.subTest(value=value):
                self.assertEqual(
                    self.provider._determine_interview_date(value), (expected, "")
                )

    def test_missing_or_invalid_base_uses_existing_fallback_plus_two_days(self):
        for value in (None, "", "不明", "invalid-date", float("nan"), pd.NaT):
            with self.subTest(value=value):
                self.assertEqual(
                    self.provider._determine_interview_date(value),
                    (datetime(2022, 5, 2), ""),
                )

    def make_prompt(self, disclosed="診断日：2022-04-20", onset="2022-04-18",
                    infection="2022-04-16", saved_date=None):
        row = {
            "ID": 1, "氏名": "テスト患者",
            "調査開始時点で開示されている情報": disclosed,
            "発症日": onset, "感染日": infection,
            datetime(2022, 4, 20): "当日の行動",
            datetime(2022, 4, 22): "二日後の行動",
            datetime(2022, 4, 23): "三日後の行動",
        }
        self.provider.df = pd.DataFrame([row])
        self.provider.target_columns = list(row)
        template = SimpleNamespace(prompt_text="本日は{interview_date_str}です。")
        with patch("modelDatabase.PromptSessionLocal"), \
                patch("modelPrompt.PromptTemplateService") as service:
            service.return_value.get_active_template.return_value = template
            return self.provider.get_patient_prompt_chunks("1", saved_date)

    def test_diagnosis_takes_priority_and_limits_disclosed_actions(self):
        chunks, date = self.make_prompt()
        self.assertEqual(date, "2022年04月22日（金曜日）")
        text = "\n".join(chunks)
        self.assertIn("本日は2022年04月22日（金曜日）です。", text)
        self.assertIn("二日後の行動", text)
        self.assertNotIn("三日後の行動", text)

    def test_asymptomatic_patient_uses_diagnosis(self):
        _, date = self.make_prompt(onset=None)
        self.assertEqual(date, "2022年04月22日（金曜日）")

    def test_missing_diagnosis_preserves_base_date_priority(self):
        for onset, infection, expected in [
            ("2022-04-18", "2022-04-16", "2022年04月20日（水曜日）"),
            (None, "2022-04-16", "2022年04月18日（月曜日）"),
            (None, None, "2022年05月02日（月曜日）"),
        ]:
            with self.subTest(onset=onset, infection=infection):
                _, date = self.make_prompt("", onset, infection)
                self.assertEqual(date, expected)

    def test_saved_session_date_and_its_disclosure_cutoff_are_preserved(self):
        saved = "2022年04月20日（水曜日）（午後・夜間）"
        chunks, date = self.make_prompt(saved_date=saved)
        self.assertEqual(date, saved)
        self.assertIn("当日の行動", "\n".join(chunks))
        self.assertNotIn("二日後の行動", "\n".join(chunks))


if __name__ == "__main__":
    unittest.main()
