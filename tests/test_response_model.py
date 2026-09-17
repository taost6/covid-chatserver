"""Responses model provenance without calling either OpenAI API or an external DB."""
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from modelSession import Base, Session as SessionRow, record_response_model
from modelUserDef import AssistantDef
from openai_assistant import OpenAIAssistantWrapper


class ResponseModelTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.response = SimpleNamespace(id='response-1', model='gpt-4.1-2025-04-14',
                                        output=[], output_text='回答', usage=None)
        # No beta attribute: any accidental Assistants API access fails the test.
        self.client = SimpleNamespace(responses=SimpleNamespace(create=AsyncMock(return_value=self.response)))
        with patch('openai_assistant.openai_get_apikey', return_value='test'), \
                patch('openai_assistant.AsyncOpenAI', return_value=self.client):
            self.wrapper = OpenAIAssistantWrapper(SimpleNamespace(apikey_storage='unused'))
        self.wrapper._check_and_wait_for_rate_limits = AsyncMock()
        self.assistant = AssistantDef(user_id='ai', role='患者', assistant_id='legacy-unused')

    async def test_uses_db_prompt_and_records_returned_model_without_assistants_api(self):
        self.assistant.thread_id = await self.wrapper.create_thread()
        await self.wrapper.add_message_to_thread(self.assistant.thread_id, 'managed patient prompt')
        result, _ = await self.wrapper.send_message(self.assistant, '質問')
        self.assertEqual(result, '回答')
        request = self.client.responses.create.call_args.kwargs
        self.assertEqual(request['model'], 'gpt-4.1')
        self.assertEqual(request['input'][0]['content'], 'managed patient prompt')
        self.assertNotIn('instructions', request)
        self.assertEqual(self.assistant.last_response_model, 'gpt-4.1-2025-04-14')
        self.assertNotIn('last_response_model', self.assistant.model_dump())

    async def test_configured_and_explicit_models_do_not_leak_across_calls(self):
        self.wrapper.config.patient_model = 'configured-model'
        await self.wrapper.send_message(self.assistant, '質問', model='batch-model', instructions='managed rubric')
        request = self.client.responses.create.call_args.kwargs
        self.assertEqual(request['model'], 'batch-model')
        self.assertEqual(request['instructions'], 'managed rubric')
        await self.wrapper.send_message(self.assistant, '次の質問')
        self.assertEqual(self.client.responses.create.call_args.kwargs['model'], 'configured-model')

    async def test_failed_call_does_not_reuse_previous_model(self):
        await self.wrapper.send_message(self.assistant, '質問')
        self.client.responses.create.side_effect = RuntimeError('test failure')
        result, _ = await self.wrapper.send_message(self.assistant, '質問', max_retries=0)
        self.assertTrue(result.startswith('FAILED:'))
        self.assertIsNone(self.assistant.last_response_model)

    async def test_record_model_updates_only_observed_role_and_keeps_historical_unknown(self):
        engine = create_engine('sqlite://')
        Base.metadata.create_all(engine)
        try:
            with Session(engine) as db:
                db.add(SessionRow(session_id='test', user_name='tester', user_role='保健師',
                                  patient_model='UNKNOWN_MODEL', evaluator_model='EVALUATOR_ERROR'))
                db.commit()
                record_response_model(db, 'test', self.assistant)
                self.assertEqual(db.query(SessionRow).one().patient_model, 'UNKNOWN_MODEL')
                await self.wrapper.send_message(self.assistant, '質問')
                record_response_model(db, 'test', self.assistant)
                row = db.query(SessionRow).one()
                self.assertEqual(row.patient_model, self.response.model)
                self.assertIsNone(row.interviewer_model)
                self.assertEqual(row.evaluator_model, 'EVALUATOR_ERROR')
        finally:
            engine.dispose()


if __name__ == '__main__':
    unittest.main()
