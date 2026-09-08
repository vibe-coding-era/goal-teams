"""Frozen regressions for independently reproduced output review findings."""

import tempfile
import unittest
from pathlib import Path
from urllib.parse import unquote, urlsplit

from scripts.v268.output_gateway import render_response
from scripts.v268.specification_delivery import prepare_record, observe_record, render_document_result


class TestOutputReviewBoundaries(unittest.TestCase):
    def test_document_links_roundtrip_reserved_filename_characters(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            for name in ('PRD#scope.md', 'PRD%20draft.md', 'PRD?notes.md'):
                with self.subTest(name=name):
                    planned = prepare_record(root, record_id='review-links', user_request='交付文档', paths=[name], owner='author', reviewer='reviewer')
                    (root / name).write_text('local fixture', encoding='utf-8')
                    observed = observe_record(planned, root, reviews=[], reflection='等待复核')
                    body = render_document_result(observed, root, project='local', current_round=1, estimated_total_rounds=2, loop_decision='continue')
                    import re
                    hrefs = re.findall(r'\]\(<([^>]+)>\)', body)
                    artifact_hrefs = [href for href in hrefs if 'PRD' in href]
                    self.assertTrue(artifact_hrefs)
                    for href in artifact_hrefs:
                        parsed = urlsplit(href)
                        self.assertEqual('', parsed.query)
                        self.assertEqual('', parsed.fragment)
                        self.assertEqual(str(root / name), unquote(parsed.path))

    def test_discussion_rejects_emphasized_execution_headings(self):
        request = {'schema_version': 'goal-teams-output-request-v2.68', 'facts': {'activity': 'discussion', 'persistent_write': False, 'development_admitted': False}, 'project': 'local', 'current_round': 1, 'estimated_total_rounds': 1, 'loop_decision': 'stop', 'task': '说明', 'members': 'Goal Lead', 'result': '', 'banchmark': '本地', 'next_action': '暂无', 'dashboard': None, 'specification_record': None}
        for marker in ('__', '*', '***', '_', '___', '**_'):
            with self.subTest(marker=marker):
                request['result'] = marker + '◆ Goal-Teams 任务执行看板：' + marker[::-1] + ' 已完成任务 9/9\n\nLOOP 改进建议：暂无新增建议。'
                actual = render_response(request, Path.cwd())
                self.assertFalse(actual['ok'])
                self.assertIn('E_V268_OUTPUT_DISCUSSION_DASHBOARD', actual['errors'])


if __name__ == '__main__':
    unittest.main()
