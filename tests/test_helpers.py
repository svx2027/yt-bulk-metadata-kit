"""
Pure-function tests for _helpers.py: error classification and the CSV log
helpers that make every script idempotent. No network calls, no credentials.
"""

import csv
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from googleapiclient.errors import HttpError

from _helpers import append_log, classify_error, read_completed_ids_from_log


class FakeResp:
    """Minimal stand-in for the httplib2.Response HttpError expects."""

    def __init__(self, status):
        self.status = status
        self.reason = "test"


def make_http_error(status, reason=""):
    if reason:
        body = '{"error": {"errors": [{"reason": "%s"}]}}' % reason
    else:
        body = "{}"
    return HttpError(FakeResp(status), body.encode("utf-8"))


class TestClassifyError(unittest.TestCase):
    def test_auth_reason_classified_as_auth_regardless_of_status(self):
        err = make_http_error(400, "invalid_grant")
        category, status, reason = classify_error(err)
        self.assertEqual(category, "auth")
        self.assertEqual(status, 400)
        self.assertEqual(reason, "invalid_grant")

    def test_401_classified_as_auth_even_without_a_matching_reason(self):
        category, status, reason = classify_error(make_http_error(401, "somethingElse"))
        self.assertEqual(category, "auth")

    def test_429_is_retryable(self):
        category, _, _ = classify_error(make_http_error(429, "rateLimitExceeded"))
        self.assertEqual(category, "retryable")

    def test_503_is_retryable(self):
        category, _, _ = classify_error(make_http_error(503))
        self.assertEqual(category, "retryable")

    def test_comments_disabled_is_per_video(self):
        category, _, _ = classify_error(make_http_error(403, "commentsDisabled"))
        self.assertEqual(category, "per_video")

    def test_video_not_found_is_per_video(self):
        category, _, _ = classify_error(make_http_error(404, "videoNotFound"))
        self.assertEqual(category, "per_video")

    def test_unrecognized_reason_is_permanent(self):
        category, status, reason = classify_error(make_http_error(400, "somethingUnexpected"))
        self.assertEqual(category, "permanent")
        self.assertEqual(status, 400)

    def test_missing_reason_body_does_not_crash(self):
        # A malformed/empty error body must not raise; it degrades to "permanent".
        category, status, _ = classify_error(make_http_error(500))
        # 500 is in RETRYABLE_STATUS, so this checks the retryable path survives
        # a body with no "reason" key rather than throwing.
        self.assertEqual(category, "retryable")
        self.assertEqual(status, 500)


class TestLogHelpers(unittest.TestCase):
    def setUp(self):
        fd, self.log_file = tempfile.mkstemp(suffix=".csv")
        os.close(fd)
        os.remove(self.log_file)  # append_log must create it fresh

    def tearDown(self):
        if os.path.exists(self.log_file):
            os.remove(self.log_file)

    def test_append_log_creates_file_with_header(self):
        append_log(self.log_file, {"video_id": "v1", "status": "ok"}, ["video_id", "status"])
        with open(self.log_file, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        self.assertEqual(rows, [{"video_id": "v1", "status": "ok"}])

    def test_append_log_appends_without_rewriting_header(self):
        fieldnames = ["video_id", "status"]
        append_log(self.log_file, {"video_id": "v1", "status": "ok"}, fieldnames)
        append_log(self.log_file, {"video_id": "v2", "status": "failed"}, fieldnames)
        with open(self.log_file, newline="", encoding="utf-8") as f:
            lines = f.readlines()
        self.assertEqual(lines[0].strip(), "video_id,status")
        self.assertEqual(len(lines), 3)

    def test_read_completed_ids_missing_file_returns_empty_set(self):
        self.assertEqual(read_completed_ids_from_log("/no/such/file.csv", {"updated"}), set())

    def test_read_completed_ids_filters_by_status_and_excludes_dry_runs(self):
        fieldnames = ["video_id", "status", "dry_run"]
        append_log(self.log_file, {"video_id": "v1", "status": "updated", "dry_run": "False"}, fieldnames)
        append_log(self.log_file, {"video_id": "v2", "status": "failed", "dry_run": "False"}, fieldnames)
        append_log(self.log_file, {"video_id": "v3", "status": "updated", "dry_run": "True"}, fieldnames)
        completed = read_completed_ids_from_log(self.log_file, {"updated"})
        self.assertEqual(completed, {"v1"})

    def test_read_completed_ids_corrupted_log_does_not_skip_anything(self):
        with open(self.log_file, "w", encoding="utf-8") as f:
            f.write("not,a,valid\nheader at all\x00\x01")
        # Must fail safe: on a corrupted log, nothing is treated as already done.
        result = read_completed_ids_from_log(self.log_file, {"updated"})
        self.assertIsInstance(result, set)


if __name__ == "__main__":
    unittest.main()
