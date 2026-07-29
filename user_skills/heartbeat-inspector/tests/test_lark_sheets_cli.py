#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import unittest
from unittest.mock import patch

from scripts.lark_sheets_cli import LarkSheetsCLI, LarkSheetsError, _parse_json_from_stdout


class TestParseJsonFromStdout(unittest.TestCase):
    def test_parses_json_with_prepended_env_logs(self):
        stdout = "[env] using profile prod\nINFO boot ok\n{\"code\":0,\"data\":{\"valueRange\":{\"values\":[[\"ok\"]]}},\"msg\":\"success\"}\n"
        obj = _parse_json_from_stdout(stdout)
        self.assertEqual(obj["code"], 0)
        self.assertEqual(obj["data"]["valueRange"]["values"], [["ok"]])

    def test_parses_json_with_trailing_log_suffix(self):
        stdout = '{"ok":true,"data":{"updatedRange":"sheet1!A2:F2"}}\nexitCode=0\n'
        obj = _parse_json_from_stdout(stdout)
        self.assertTrue(obj["ok"])
        self.assertEqual(obj["data"]["updatedRange"], "sheet1!A2:F2")

    def test_raises_on_non_json_stdout(self):
        with self.assertRaises(json.JSONDecodeError):
            _parse_json_from_stdout("INFO only logs without payload")


class TestLarkSheetsCliRun(unittest.TestCase):
    @patch("scripts.lark_sheets_cli.subprocess.run")
    def test_run_accepts_noisy_stdout(self, mock_run):
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = "[env] source /etc/profile\n{\"ok\":true,\"data\":{\"sheets\":{\"sheets\":[]}}}\n"
        mock_run.return_value.stderr = ""

        cli = LarkSheetsCLI(cli_path="/bin/echo")
        obj = cli._run(["fake"])

        self.assertTrue(obj["ok"])

    @patch("scripts.lark_sheets_cli.subprocess.run")
    def test_run_raises_on_invalid_stdout(self, mock_run):
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = "[env] only logs"
        mock_run.return_value.stderr = ""

        cli = LarkSheetsCLI(cli_path="/bin/echo")
        with self.assertRaises(LarkSheetsError):
            cli._run(["fake"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
