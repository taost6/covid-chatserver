"""No external DB or LLM calls: verify version preservation and safe replay."""
import json
from pathlib import Path
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from modelPrompt import Base, PromptTemplate, PromptTemplateService
from tools.register_prompt_revision import register


class PromptRevisionTest(unittest.TestCase):
    def setUp(self):
        self.revision = json.loads((Path(__file__).resolve().parents[1] /
            'prompt_migrations/patient_dialogue_20260914.json').read_text(encoding='utf-8'))
        self.engine = create_engine('sqlite://')
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.db.add(PromptTemplate(template_type='patient', version=self.revision['expected_version'],
            prompt_text=self.revision['expected_prompt_text'], message_text=self.revision['expected_message_text'],
            is_active=True))
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_new_version_preserves_old_prompt_and_greeting(self):
        result = register(self.db, self.revision, True)
        service = PromptTemplateService(self.db)
        old = service.get_template_by_version('patient', self.revision['expected_version'])
        self.assertEqual(old.prompt_text, self.revision['expected_prompt_text'])
        self.assertEqual(old.message_text, self.revision['expected_message_text'])
        self.assertFalse(old.is_active)
        new = service.get_active_template('patient')
        self.assertEqual(new.version, result['version'])
        self.assertEqual(new.prompt_text, self.revision['prompt_text'])
        self.assertEqual(new.message_text.replace('{patient_name}', '川原'), '川原です。よろしくお願いします。')

    def test_preview_does_not_write_and_retry_does_not_duplicate(self):
        self.assertEqual(register(self.db, self.revision)['status'], 'preview')
        self.assertEqual(self.db.query(PromptTemplate).count(), 1)
        register(self.db, self.revision, True)
        self.assertEqual(register(self.db, self.revision, True)['status'], 'already_applied')
        self.assertEqual(self.db.query(PromptTemplate).count(), 2)

    def test_concurrent_edit_is_not_overwritten(self):
        self.db.query(PromptTemplate).first().prompt_text = '別の変更'
        self.db.commit()
        with self.assertRaises(ValueError):
            register(self.db, self.revision, True)
        self.assertEqual(self.db.query(PromptTemplate).count(), 1)

    def merge_fixture(self):
        revision = json.loads((Path(__file__).resolve().parents[1] /
            'prompt_migrations/evaluator_20260917.json').read_text(encoding='utf-8'))
        self.db.add(PromptTemplate(id=revision['expected_active_id'], template_type='evaluator',
            version=revision['expected_active_version'], prompt_text='old binary prompt', is_active=True))
        self.db.add(PromptTemplate(id=revision['source_id'], template_type=revision['source_type'],
            version=revision['source_version'], prompt_text=revision['prompt_text'],
            message_text=revision['message_text'], is_active=True))
        self.db.commit()
        return revision

    def test_merge_preserves_text_and_history_without_activating_before_deployment(self):
        revision = self.merge_fixture()
        result = register(self.db, revision, True)
        service = PromptTemplateService(self.db)
        self.assertEqual(result['version'], 13)
        self.assertEqual(service.get_active_template('evaluator').version, 12)
        self.assertEqual(service.get_template_by_version('evaluator', 12).prompt_text, 'old binary prompt')
        new = service.get_template_by_version('evaluator', 13)
        self.assertEqual(new.id, revision['source_id'])
        self.assertEqual(new.prompt_text, revision['prompt_text'])
        self.assertFalse(new.is_active)
        self.assertEqual(self.db.query(PromptTemplate).filter_by(template_type=revision['source_type']).count(), 0)
        self.assertEqual(register(self.db, revision, True)['status'], 'already_applied')

    def test_merge_preview_does_not_mutate(self):
        revision = self.merge_fixture()
        self.assertEqual(register(self.db, revision)['status'], 'preview')
        self.assertIsNotNone(PromptTemplateService(self.db).get_active_template(revision['source_type']))

    def test_merge_refuses_new_source_edits(self):
        revision = self.merge_fixture()
        self.db.get(PromptTemplate, revision['source_id']).prompt_text = 'a new edit'
        self.db.commit()
        with self.assertRaises(ValueError):
            register(self.db, revision, True)
        self.assertIsNotNone(PromptTemplateService(self.db).get_active_template(revision['source_type']))

    def test_three_grade_revision_uses_same_evaluator_and_preserves_v13(self):
        revision = json.loads((Path(__file__).resolve().parents[1] /
            'prompt_migrations/evaluator_three_grades_20260917.json').read_text(encoding='utf-8'))
        self.db.add(PromptTemplate(template_type='evaluator', version=13,
            prompt_text=revision['expected_prompt_text'], message_text=revision['expected_message_text'], is_active=True))
        self.db.commit()
        result = register(self.db, revision, True)
        self.assertEqual(result['version'], 14)
        service = PromptTemplateService(self.db)
        self.assertEqual(service.get_template_by_version('evaluator', 13).prompt_text, revision['expected_prompt_text'])
        self.assertEqual(service.get_active_template('evaluator').prompt_text, revision['prompt_text'])
        self.assertIn('三種類だけ', service.get_active_template('evaluator').prompt_text)
        self.assertEqual(register(self.db, revision, True)['status'], 'already_applied')


if __name__ == '__main__':
    unittest.main()
