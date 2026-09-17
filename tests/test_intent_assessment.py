import copy
import json
import unittest
from unittest.mock import AsyncMock, patch
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from intent_assessment import make_input, summarize, validate_assessment, input_hash
from intent_assessment_service import ensure_assessment, saved_result, assessment_settings, assess, AssessmentOutputError
from modelIRT import IRTAssessmentRun, IRTResponseJudgment, IRTPatientInstance, Base
from modelSession import Session as SessionRow
from modelPrompt import Base as PromptBase, PromptTemplate
from modelDatabase import ChatLog


def fixture():
    payload = make_input(dict(session_id='s', patient_id='60', interview_date='2022年04月22日（金曜日）'),
                         [dict(id=1, item_type_code='T-3', instance_number=1, description='同僚の体調')],
                         [dict(id=10, sender='Assistant', ai_role='患者', message='こんにちは。', is_initial_message=True),
                          dict(id=11, sender='User', user_role='保健師', message='同僚の体調はどうでしたか。'),
                          dict(id=12, sender='Assistant', ai_role='患者', message='喉が痛いと言っていました。')])
    raw = dict(judgments=[dict(instance_id=1, grade='full', question_message_ids=[11], answer_message_ids=[12],
                              confidence=0.9, reason='同僚の体調を質問し、その場で聞いた症状を把握した。')],
               acts=[dict(message_id=11, kind='question', quote='同僚の体調はどうでしたか。')])
    return payload, raw


class IntentValidationTest(unittest.TestCase):
    def test_full_without_question_mark(self):
        payload, raw = fixture()
        out = summarize(raw, payload)
        self.assertEqual(out['score'], 1)
        self.assertEqual((out['display_message_count'], out['message_count']), (3, 2))
        self.assertEqual((out['question_count'], out['legacy_question_mark_count']), (1, 0))

    def test_incidental_is_distinct_from_missing_and_not_correct(self):
        payload, raw = fixture()
        raw['judgments'][0].update(grade='incidental', question_message_ids=[])
        out = summarize(raw, payload)
        self.assertEqual(out['incidental_item_count'], 1)
        self.assertEqual(out['missing_item_count'], 0)
        self.assertFalse(out['items'][0]['collected'])
        self.assertEqual(out['score'], 0)

    def test_pending_does_not_silently_become_a_miss(self):
        payload, raw = fixture()
        raw['judgments'][0]['grade'] = 'pending'
        out = summarize(raw, payload)
        self.assertIsNone(out['score'])
        self.assertEqual(out['assessed_item_count'], 0)
        self.assertEqual(out['missing_item_count'], 0)

    def test_evidence_constraints(self):
        payload, raw = fixture()
        bad = [dict(question_message_ids=[]), dict(answer_message_ids=[]),
               dict(answer_message_ids=[10]), dict(answer_message_ids=[11]),
               dict(question_message_ids=[12]), dict(question_message_ids=[999]), dict(answer_message_ids=[999])]
        for change in bad:
            with self.subTest(change=change):
                test = copy.deepcopy(raw)
                test['judgments'][0].update(change)
                result = summarize(test, payload)
                self.assertEqual(result['items'][0]['grade'], 'pending')
                self.assertIn('根拠に不整合', result['items'][0]['reason'])
                self.assertEqual(result['collected_item_count'], 0)
                self.assertIsNone(result['score'])
        for change in (dict(grade='invented'), dict(confidence=2), dict(instance_id=999)):
            with self.subTest(change=change):
                test = copy.deepcopy(raw)
                test['judgments'][0].update(change)
                with self.assertRaises(ValueError):
                    validate_assessment(test, payload)

    def test_duplicate_and_missing_item_results_are_rejected(self):
        payload, raw = fixture()
        for judgments in ([], raw['judgments'] * 2):
            with self.assertRaises(ValueError):
                validate_assessment({**raw, 'judgments': judgments}, payload)

    def test_quotes_are_exact_and_cover_every_nurse_message(self):
        payload, raw = fixture()
        for acts in ([], raw['acts']*2, [dict(message_id=11, kind='question', quote='同僚の体調')],
                     [dict(message_id=11, kind='question', quote='同僚の体調は？')]):
            with self.assertRaises(ValueError):
                validate_assessment({**raw, 'acts': acts}, payload)

    def test_acknowledgment_is_not_evidence_of_focused_confirmation(self):
        payload, raw = fixture()
        raw['acts'][0]['kind'] = 'other'
        payload['items'].append({**payload['items'][0], 'id': 2})
        raw['judgments'].append({**raw['judgments'][0], 'instance_id': 2, 'grade': 'incidental',
                                 'question_message_ids': []})
        result = validate_assessment(raw, payload)
        self.assertEqual([j['grade'] for j in result['judgments']], ['pending', 'incidental'])
        self.assertEqual(result['judgments'][0]['question_message_ids'], [])
        self.assertEqual(result['acts'][0]['kind'], 'other')
        self.assertEqual(raw['judgments'][0]['grade'], 'full')
        self.assertEqual(raw['judgments'][0]['question_message_ids'], [11])
        self.assertEqual(validate_assessment(result, payload), result)

    def test_explanation_evidence_does_not_become_a_question(self):
        payload, raw = fixture()
        raw['acts'][0]['kind'] = 'explanation'
        result = summarize(raw, payload)
        self.assertEqual(result['pending_item_count'], 1)
        self.assertEqual(result['question_count'], 0)
        self.assertEqual(result['explanation_count'], 1)

    def test_full_without_a_following_patient_reply_is_held_pending(self):
        payload, raw = fixture()
        payload['dialogue'] = [payload['dialogue'][0], payload['dialogue'][2], payload['dialogue'][1]]
        result = summarize(raw, payload)
        self.assertEqual(result['pending_item_count'], 1)
        self.assertEqual(result['collected_item_count'], 0)

    def test_incidental_without_patient_evidence_is_held_pending(self):
        payload, raw = fixture()
        raw['judgments'][0].update(grade='incidental', answer_message_ids=[])
        self.assertEqual(summarize(raw, payload)['pending_item_count'], 1)

    def test_explanation_and_question_are_separate_acts(self):
        payload, raw = fixture()
        payload['dialogue'][1]['text'] = '調査のため伺います。同僚の体調はどうでしたか。'
        raw['acts'].insert(0, dict(message_id=11, kind='explanation', quote='調査のため伺います。'))
        out = summarize(raw, payload)
        self.assertEqual((out['nurse_turn_count'], out['question_count'], out['explanation_count']), (1, 1, 1))

    def test_calendar_uses_scenario_date_not_execution_date(self):
        payload, _ = fixture()
        self.assertIn(dict(date='2022-04-16', weekday='土'), payload['calendar'])
        self.assertIn(dict(date='2022-04-17', weekday='日'), payload['calendar'])
        bad = make_input(dict(session_id='s', patient_id='60', interview_date='不明'),
                         [dict(id=1, item_type_code='T-3', instance_number=1)],
                         [dict(id=1, sender='User', user_role='保健師', message='質問')])
        self.assertEqual(bad['calendar'], [])

    def test_frozen_input_hash_changes_with_item_or_interview_date(self):
        payload, _ = fixture()
        changed = copy.deepcopy(payload)
        changed['items'][0]['description'] += '修正'
        self.assertNotEqual(input_hash(payload), input_hash(changed))
        changed = {**payload, 'interview_date': '2022-04-23'}
        self.assertNotEqual(input_hash(payload), input_hash(changed))



class PersistenceTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://')
        PromptBase.metadata.create_all(self.engine)
        Base.metadata.create_all(self.engine)
        SessionRow.metadata.create_all(self.engine)
        ChatLog.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.db.add(PromptTemplate(template_type='evaluator', version=1, prompt_text='managed test rubric', is_active=True))
        self.db.add(SessionRow(session_id='s', user_name='test', user_role='保健師', patient_id='60',
                               interview_date='2022年04月22日（金曜日）'))
        self.db.add(IRTPatientInstance(id=1, patient_id='60', item_type_code='T-3', instance_number=1,
                                      description='同僚の体調', catalog_version=1))
        self.db.add(ChatLog(id=11, session_id='s', sender='User', user_role='保健師', message='同僚の体調はどうでしたか。'))
        self.db.add(ChatLog(id=12, session_id='s', sender='Assistant', ai_role='患者', message='喉が痛いと言っていました。'))
        self.db.add(IRTResponseJudgment(session_id='s', instance_id=1, is_correct=False))
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    async def test_new_run_preserves_legacy_and_reuses_cached_result(self):
        _, raw = fixture()
        with patch('intent_assessment_service.assess', AsyncMock(return_value=raw)) as call:
            first = await ensure_assessment(self.db, 's', None, evaluator_model='test-model')
            second = await ensure_assessment(self.db, 's', None, evaluator_model='test-model')
        self.assertEqual(call.await_count, 1)
        self.assertEqual(first['score'], second['score'])
        self.assertFalse(self.db.query(IRTResponseJudgment).one().is_correct)
        self.assertEqual(self.db.query(IRTAssessmentRun).count(), 1)
        self.db.query(IRTPatientInstance).one().description = 'different future definition'
        self.db.commit()
        self.assertEqual(saved_result(self.db.query(IRTAssessmentRun).one())['items'][0]['description'], '同僚の体調')

    async def test_failed_call_does_not_destroy_or_partially_replace_legacy(self):
        with patch('intent_assessment_service.assess', AsyncMock(side_effect=ValueError('invalid evidence'))):
            with self.assertRaises(ValueError):
                await ensure_assessment(self.db, 's', None, evaluator_model='test-model')
        self.db.rollback()
        self.assertEqual(self.db.query(IRTAssessmentRun).count(), 0)
        self.assertEqual(self.db.query(IRTResponseJudgment).count(), 1)

    async def test_pending_correction_preserves_original_output_and_is_cached(self):
        payload, raw = fixture()
        raw['acts'][0]['kind'] = 'other'
        with patch('intent_assessment_service.assess', AsyncMock(return_value=raw)) as call:
            first = await ensure_assessment(self.db, 's', None, evaluator_model='test-model')
            second = await ensure_assessment(self.db, 's', None, evaluator_model='test-model')
            self.assertEqual(call.await_count, 1)
        self.assertEqual(first, second)
        self.assertEqual(first['pending_item_count'], 1)
        stored = json.loads(self.db.query(IRTAssessmentRun).one().result_json)
        self.assertEqual(stored['model_output'], raw)
        self.assertEqual(stored['model_output']['judgments'][0]['grade'], 'full')
        self.assertEqual(stored['assessment']['judgments'][0]['grade'], 'pending')
        self.assertEqual(self.db.query(IRTResponseJudgment).count(), 1)

    async def test_flat_historical_result_remains_readable(self):
        payload, raw = fixture()
        result = saved_result(SimpleNamespace(result_json=json.dumps(raw), input_json=json.dumps(payload)))
        self.assertEqual(result['collected_item_count'], 1)
        self.assertEqual(result['pending_item_count'], 0)

    async def test_incomplete_classification_is_reported_without_saving(self):
        _, raw = fixture()
        raw['acts'] = []
        with patch('intent_assessment_service.assess', AsyncMock(return_value=raw)):
            with self.assertRaises(AssessmentOutputError):
                await ensure_assessment(self.db, 's', None, evaluator_model='test-model')
        self.assertEqual(self.db.query(IRTAssessmentRun).count(), 0)

    async def test_invalid_json_and_missing_tool_return_explicit_errors(self):
        payload, _ = fixture()
        payload['assessment'] = assessment_settings(self.db, 'selected-model')
        for call in (None, SimpleNamespace(name='submit_intent_assessment', arguments='{"judgments":')):
            wrapper = SimpleNamespace(create_thread=AsyncMock(return_value='thread'),
                delete_thread_by_id=AsyncMock(), send_message=AsyncMock(return_value=(None, call)))
            with self.assertRaises(AssessmentOutputError):
                await assess(wrapper, payload)
            wrapper.send_message.assert_awaited_once()
            wrapper.delete_thread_by_id.assert_awaited_once_with('thread')

    async def test_managed_prompt_and_selected_model_are_sent_without_hidden_rules(self):
        payload, raw = fixture()
        payload['assessment'] = assessment_settings(self.db, 'selected-model', 1)
        import json
        wrapper = SimpleNamespace(create_thread=AsyncMock(return_value='thread'),
            delete_thread_by_id=AsyncMock(), send_message=AsyncMock(return_value=(None,
                SimpleNamespace(name='submit_intent_assessment', arguments=json.dumps(raw)))))
        await assess(wrapper, payload)
        self.assertEqual(wrapper.send_message.call_args.kwargs['instructions'], 'managed test rubric')
        self.assertEqual(wrapper.send_message.call_args.kwargs['model'], 'selected-model')

    async def test_missing_managed_version_has_no_fallback(self):
        with self.assertRaises(ValueError):
            assessment_settings(self.db, 'selected-model', 999)

    async def test_retired_prompt_format_is_rejected_before_model_call(self):
        template = self.db.query(PromptTemplate).one()
        template.prompt_text = 'submit_irt_judgments を呼び出してください'
        self.db.commit()
        with patch('intent_assessment_service.assess', AsyncMock()) as call:
            with self.assertRaisesRegex(ValueError, '旧形式'):
                await ensure_assessment(self.db, 's', None, evaluator_model='test-model')
            call.assert_not_awaited()

    async def test_explicit_reassessment_appends_history_with_current_evaluator(self):
        _, raw = fixture()
        with patch('intent_assessment_service.assess', AsyncMock(return_value=raw)):
            await ensure_assessment(self.db, 's', None, evaluator_model='first-model')
            await ensure_assessment(self.db, 's', None, evaluator_model='second-model', force=True)
        runs = self.db.query(IRTAssessmentRun).all()
        self.assertEqual(len(runs), 2)
        self.assertEqual({r.evaluator_model for r in runs}, {'first-model', 'second-model'})
        self.assertEqual(self.db.query(IRTResponseJudgment).count(), 1)

    async def test_batch_uses_same_evaluator_without_mode_selection(self):
        from irt_batch_runner import IRTBatchRunner
        runner = IRTBatchRunner.__new__(IRTBatchRunner)
        runner.oaw = None
        _, raw = fixture()
        with patch('intent_assessment_service.assess', AsyncMock(return_value=raw)) as call:
            result = await runner._execute_irt_judgment_for_batch('s', self.db, 'batch-model', 1)
        self.assertEqual(call.call_args.args[1]['assessment']['prompt_type'], 'evaluator')
        self.assertEqual(call.call_args.args[1]['assessment']['model'], 'batch-model')
        self.assertEqual(result['correct_count'], 1)

    async def test_hash_tracks_prompt_and_model(self):
        payload, _ = fixture()
        payload['assessment'] = assessment_settings(self.db, 'model-a', 1)
        original = input_hash(payload)
        payload['assessment']['model'] = 'model-b'
        self.assertNotEqual(original, input_hash(payload))
        original = input_hash(payload)
        payload['assessment']['instructions'] = 'changed managed prompt'
        self.assertNotEqual(original, input_hash(payload))


if __name__ == '__main__':
    unittest.main()
