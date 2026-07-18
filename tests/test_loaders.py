import tempfile
import unittest
from pathlib import Path

from app.core.common.exception import BusiException
from app.rag import loaders


class LoadersTest(unittest.TestCase):
    def test_invalid_pdf_content_raises_busi_exception(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir).joinpath("invalid.pdf")
            path.write_bytes(b"\x00\x00\x00\x00\x00")

            with self.assertRaises(BusiException) as context:
                loaders.load_document({"object_path": path.as_posix()})

        self.assertEqual(context.exception.message, "文件内容不合法")
