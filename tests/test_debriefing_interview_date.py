"""評価レポート（デブリーフィング）が、患者AIに渡したのと同じ調査日で患者設定を作り直すことの回帰テスト。

2026-11 奥村先生指摘：調査日を「診断当日」にしたセッションで、評価AIが既定の「診断日＋2日」の設定を
受け取り、会話中の「今日」と設定上の日付が食い違うと評価した。DB・Google Drive・LLMには接続しない。
"""
import asyncio
import json
import logging
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import chatapi
from modelPrompt import Base as PromptBase, PromptTemplate
from modelSession import Session as SessionRow

SAVED_DATE = '2022年04月24日（日曜日）（午後・夜間）'


class DebriefingInterviewDateTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
        for metadata in (SessionRow.metadata, PromptBase.metadata):
            metadata.create_all(self.engine)
        self.factory = sessionmaker(bind=self.engine)
        with self.factory() as db:
            db.add(PromptTemplate(template_type='debriefing', version=1, prompt_text='評価ルール', is_active=True))
            db.add(SessionRow(session_id='s1', user_name='tester', user_role='保健師', patient_id='62',
                              interview_date=SAVED_DATE))
            db.commit()

    def tearDown(self):
        self.engine.dispose()

    def run_debriefing(self):
        db = self.factory()
        role_provider = MagicMock()
        role_provider.get_patient_details.return_value = {'name': '山田 翔太'}
        role_provider.get_patient_prompt_chunks.return_value = (['設定'], SAVED_DATE)
        role_provider._split_text_for_prompt.side_effect = lambda text, n: [text]
        call = SimpleNamespace(name='submit_debriefing_report', arguments=json.dumps({'overall_score': 80}))
        oaw = SimpleNamespace(create_thread=AsyncMock(return_value='t'), add_message_to_thread=AsyncMock(),
                              send_message=AsyncMock(return_value=(None, call)),
                              delete_thread=AsyncMock(), delete_thread_by_id=AsyncMock())
        user = SimpleNamespace(role='保健師', user_name='tester', target_patient_id='62',
                               ws=SimpleNamespace(send_json=AsyncMock()))
        history = SimpleNamespace(history=[SimpleNamespace(role='保健師', text='今日の体調は？'),
                                           SimpleNamespace(role='患者', text='元気です。')])
        session = SimpleNamespace(session_id='s1', users=[user], history=history)
        with patch('chatapi.modelDatabase.PromptSessionLocal', self.factory), \
                patch('chatapi.record_response_model'), patch('chatapi.log_message', AsyncMock()):
            asyncio.run(chatapi._execute_debriefing_with_specialist(
                session, user, db, logging.getLogger('test'), oaw, role_provider))
        db.close()
        return role_provider

    def test_uses_interview_date_saved_for_the_session(self):
        role_provider = self.run_debriefing()
        args, kwargs = role_provider.get_patient_prompt_chunks.call_args
        self.assertEqual(args[:2], ('62', SAVED_DATE))


if __name__ == '__main__':
    unittest.main()
