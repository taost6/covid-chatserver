import logging
import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import chatapi
from modelPrompt import Base as PromptBase, PromptTemplate
from modelDatabase import ChatLog
from modelIRT import Base, IRTResponseJudgment, IRTAssessmentRun, IRTPatientInstance
from modelSession import Session as SessionRow


class IntentApiTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
        for metadata in (Base.metadata, ChatLog.metadata, SessionRow.metadata, PromptBase.metadata):
            metadata.create_all(self.engine)
        self.factory = sessionmaker(bind=self.engine)
        with self.factory() as db:
            db.add(PromptTemplate(template_type='evaluator', version=1, prompt_text='managed test rubric', is_active=True))
            db.add(SessionRow(session_id='test', user_name='tester', user_role='保健師', patient_id='60',
                              interview_date='2022年04月22日（金曜日）'))
            db.add(IRTPatientInstance(id=1, patient_id='60', item_type_code='T-3', instance_number=1,
                                     description='同僚の体調', catalog_version=1))
            db.add(ChatLog(id=1, session_id='test', sender='User', user_role='保健師', message='同僚の体調は？'))
            db.add(ChatLog(id=2, session_id='test', sender='Assistant', ai_role='患者', message='喉が痛いそうです。'))
            db.commit()
        self.raw = dict(judgments=[dict(instance_id=1, grade='full', question_message_ids=[1], answer_message_ids=[2],
                                       confidence=0.9, reason='対象に向けた質問と回答あり')],
                        acts=[dict(message_id=1, kind='question', quote='同僚の体調は？')])
        self.patches = [patch('modelDatabase.SessionLocal', self.factory),
                        patch('chatapi.OpenAIAssistantWrapper'), patch('chatapi.PatientRoleProvider'),
                        patch.dict(os.environ, {'CBT_ADMIN_KEY': 'test-key'})]
        for p in self.patches:
            p.start()
        # Without a lifespan context, no startup DB/Drive initialization runs.
        app = chatapi.api(SimpleNamespace(logger=logging.getLogger('test')))
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        for p in reversed(self.patches):
            p.stop()
        self.engine.dispose()

    def test_readonly_endpoint_never_calls_model(self):
        from sqlalchemy.orm import Session as SQLSession
        from sqlalchemy.sql.elements import TextClause
        with self.factory() as db:
            db.add(IRTResponseJudgment(session_id='test', instance_id=1, is_correct=True))
            db.commit()
        execute = SQLSession.execute
        def compatible_execute(db, statement, *args, **kwargs):
            # The existing history metrics query uses PostgreSQL ANY/FILTER.
            if isinstance(statement, TextClause) and 'ANY(:ids)' in str(statement):
                return [SimpleNamespace(session_id='test', total_msgs=2, nurse_msgs=1, questions=1)]
            return execute(db, statement, *args, **kwargs)
        with patch.object(SQLSession, 'execute', compatible_execute), \
                patch('intent_assessment_service.assess', AsyncMock()) as call:
            response = self.client.get('/v1/irt/session/test/result')
            self.assertEqual(response.status_code, 200, response.text)
            self.assertIsNone(response.json()['assessment_version'])
            self.assertTrue(response.json()['items'][0]['collected'])
            call.assert_not_awaited()

    def test_batch_no_longer_accepts_a_legacy_mode_switch(self):
        response = self.client.post('/v1/irt/batch/start', json={
            'patient_ids': ['60'], 'assessment_mode': 'legacy'})
        self.assertEqual(response.status_code, 422)

    def test_removed_parallel_endpoints_do_not_run(self):
        with patch('intent_assessment_service.assess', AsyncMock()) as call:
            self.assertEqual(self.client.get('/v1/irt/session/test/intent').status_code, 404)
            self.assertIn(self.client.post('/v1/irt/session/test/intent').status_code, (404, 405))
            call.assert_not_awaited()

    def test_explicit_new_assessment_requires_admin_and_preserves_old(self):
        with self.factory() as db:
            db.add(IRTResponseJudgment(session_id='test', instance_id=1, is_correct=False))
            db.commit()
        with patch('intent_assessment_service.assess', AsyncMock(return_value=self.raw)) as call:
            self.assertEqual(self.client.post('/v1/irt/judgments/evaluate/test').status_code, 403)
            response = self.client.post('/v1/irt/judgments/evaluate/test', headers={'X-Admin-Key': 'test-key'})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()['items'][0]['grade'], 'full')
            again = self.client.get('/v1/irt/session/test/result')
            self.assertEqual(again.json()['assessment_version'], 'intent-1')
            self.assertEqual(call.await_count, 1)
        with self.factory() as db:
            self.assertFalse(db.query(IRTResponseJudgment).one().is_correct)
            self.assertEqual(db.query(IRTAssessmentRun).count(), 1)

    def test_new_session_result_uses_evidence_based_score(self):
        with patch('intent_assessment_service.assess', AsyncMock(return_value=self.raw)):
            result = self.client.get('/v1/irt/session/test/result')
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()['question_count'], 1)
        self.assertEqual(result.json()['confirmation_count'], 0)
        self.assertEqual(result.json()['score'], 1)

    def test_pending_is_exposed_as_null_score(self):
        self.raw['judgments'][0]['grade'] = 'pending'
        with patch('intent_assessment_service.assess', AsyncMock(return_value=self.raw)):
            response = self.client.get('/v1/irt/session/test/result')
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIsNone(response.json()['score'])
        self.assertEqual(response.json()['pending_item_count'], 1)

    def test_unknown_session_returns_404_without_model_call(self):
        with patch('intent_assessment_service.assess', AsyncMock()) as call:
            self.assertEqual(self.client.get('/v1/irt/session/unknown/result').status_code, 404)
            call.assert_not_awaited()


if __name__ == '__main__':
    unittest.main()
