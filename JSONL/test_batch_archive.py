import base64
import json
from pathlib import Path
import tempfile
import io
from contextlib import redirect_stdout
import unittest
from unittest.mock import patch
import export_all_codex_chats as batch


class ArchiveRegression(unittest.TestCase):
    def test_incremental_skip_changes_and_missing_output(self):
        sid = '01a0cacf-96b5-7d51-b23e-d5b32997ad28'
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source_dir = root / 'source'
            source_dir.mkdir()
            source = source_dir / (sid + '.jsonl')
            records = [{'type': 'session_meta', 'payload': {'id': sid}},
                       {'type': 'response_item', 'payload': {'type': 'message', 'role': 'user',
                        'content': [{'type': 'input_text', 'text': 'First prompt'}]}}]
            source.write_text('\n'.join(json.dumps(r) for r in records), encoding='utf-8')
            args = [str(root / 'out'), '--source-dir', str(source_dir), '--markdown-only']
            with patch.object(batch.chat, 'find_thread_name', return_value='Example'), redirect_stdout(io.StringIO()):
                self.assertEqual(batch.main(args), 0)
                with patch.object(batch, 'export_session', wraps=batch.export_session) as export:
                    self.assertEqual(batch.main(args), 0)
                    export.assert_not_called()
                    source.write_text(source.read_text(encoding='utf-8').replace('First prompt', 'New prompt'), encoding='utf-8')
                    self.assertEqual(batch.main(args), 0)
                    self.assertEqual(export.call_count, 1)
                    md = next((root / 'out').glob('*/Example.md'))
                    self.assertIn('New prompt', md.read_text(encoding='utf-8'))
                    md.unlink()
                    self.assertEqual(batch.main(args), 0)
                    self.assertEqual(export.call_count, 2)
                    self.assertEqual(batch.main(args + ['--force']), 0)
                    self.assertEqual(export.call_count, 3)

    def test_child_cannot_overwrite_parent_and_images_resolve(self):
        parent = '01a0cacf-96b5-7d51-b23e-d5b32997ad28'
        child = '01a0cad0-8cc7-7451-b685-83070121cc96'
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            paths = []
            for identity in (parent, child):
                records = [
                    {'type': 'session_meta', 'payload': {'id': identity, 'session_id': parent, 'cwd': 'example'}},
                    {'type': 'response_item', 'payload': {'type': 'message', 'role': 'user', 'content': [
                        {'type': 'input_text', 'text': 'My prompt'},
                        {'type': 'input_image', 'image_url': 'data:image/png;base64,' + base64.b64encode(b'image-bytes').decode()}]}},
                    {'type': 'response_item', 'payload': {'type': 'reasoning', 'summary': [{'text': 'Stored summary'}]}},
                    {'type': 'response_item', 'payload': {'type': 'function_call', 'name': 'exec', 'arguments': 'BACKGROUND_COMMAND_MARKER'}},
                    {'type': 'response_item', 'payload': {'type': 'function_call_output', 'output': 'BACKGROUND_OUTPUT_MARKER'}},
                ]
                source = root / (identity + '.jsonl')
                source.write_text('\n'.join(json.dumps(r) for r in records), encoding='utf-8')
                with patch.object(batch.chat, 'find_thread_name', return_value='Same title'):
                    result = batch.export_session(source, root / 'out', None, markdown_only=True)
                paths.append(result['directory'])
                directory = root / 'out' / result['directory']
                text = (directory / 'Same title.md').read_text(encoding='utf-8')
                self.assertIn('My prompt', text)
                self.assertIn('Stored summary', text)
                self.assertEqual(text.count('My prompt'), 1)
                self.assertIn('## You\n', text)
                self.assertNotIn('BACKGROUND_COMMAND_MARKER', text)
                self.assertNotIn('BACKGROUND_OUTPUT_MARKER', text)
                self.assertNotIn('Recorded event: session_meta', text)
                self.assertEqual((directory / 'assets/1/image-001.png').read_bytes(), b'image-bytes')
                self.assertFalse(list(directory.glob('*.html')))
            self.assertNotEqual(paths[0], paths[1])


if __name__ == '__main__':
    unittest.main()
