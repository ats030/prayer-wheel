"""build.atomic_write の受け入れ基準を検証する。

- 生成内容がそのまま書き込まれ、一時生成物が残らない
- 書き込み失敗時は旧の完成ファイルを保持し、一時生成物を残さない
- 置換先と同じディレクトリの一時ファイルを使用する
- 生成される _resources.py が常に完成済みのPythonとして読める
"""
import ast
import pathlib
import tempfile
import unittest
from unittest import mock

import build


class AtomicWriteTest(unittest.TestCase):
    def setUp(self):
        self.dir = pathlib.Path(tempfile.mkdtemp(prefix="atomic_write_test."))
        self.path = self.dir / "target.py"

    def tearDown(self):
        for entry in self.dir.iterdir():
            entry.unlink()
        self.dir.rmdir()

    def leftover_temps(self):
        return [p.name for p in self.dir.iterdir() if p.name.startswith("._resources.")]

    def test_writes_same_bytes_no_temp_left_and_valid_python(self):
        text = "BUNDLE_SHA256 = 'abcd'\nRESOURCES = {'a': b'x'}\n"
        build.atomic_write(self.path, text)
        self.assertEqual(self.path.read_text(encoding="utf-8"), text)
        ast.parse(self.path.read_text(encoding="utf-8"))
        self.assertEqual(self.leftover_temps(), [])

    def test_write_failure_keeps_old_file_and_removes_temp(self):
        self.path.write_text("OLD-CONTENT\n", encoding="utf-8")
        old = self.path.read_bytes()

        def boom(data):
            raise OSError("disk full")

        fake = mock.mock_open()
        fake.return_value.write.side_effect = boom

        with mock.patch.object(build.os, "fdopen", return_value=fake.return_value) as fdopen, \
             mock.patch.object(build.os, "replace") as do_replace:
            with self.assertRaises(OSError):
                build.atomic_write(self.path, "NEW-CONTENT\n")

        do_replace.assert_not_called()
        self.assertEqual(self.path.read_bytes(), old)
        self.assertEqual(self.leftover_temps(), [])

    def test_uses_temp_in_same_directory(self):
        captured = {}

        def fake_mkstemp(prefix, suffix, dir):
            captured["dir"] = dir
            return (3, str(self.dir / (prefix + "x" + suffix)))

        with mock.patch.object(build.tempfile, "mkstemp", side_effect=fake_mkstemp), \
             mock.patch.object(build.os, "fdopen", mock.mock_open().return_value), \
             mock.patch.object(build.os, "fsync", lambda n: None), \
             mock.patch.object(build.os, "replace"):
            build.atomic_write(self.path, "x\n")

        self.assertEqual(pathlib.Path(captured["dir"]), self.dir)


if __name__ == "__main__":
    unittest.main()
