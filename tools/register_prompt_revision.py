"""Register a reviewed revision through the existing prompt management service.

Default: validate the current version and preview. --apply creates/activates one
new version, preserving old text. This file is not loaded by the application.
"""
import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, text, func
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from modelPrompt import PromptTemplate, PromptTemplateService


def merge_template_type(db, revision, apply):
    """One-time consolidation: keep the source row/text and old target versions."""
    source = db.query(PromptTemplate).filter_by(id=revision['source_id']).one()
    expected = (revision['prompt_text'], revision['message_text'])
    if (source.prompt_text, source.message_text) != expected:
        raise ValueError('Source text changed after review')
    if source.template_type == revision['template_type']:
        return dict(status='already_applied', id=source.id, version=source.version, is_active=source.is_active)
    if (source.template_type, source.version) != (revision['source_type'], revision['source_version']):
        raise ValueError('Unexpected source template')
    if db.query(PromptTemplate).filter_by(template_type=revision['source_type']).count() != 1:
        raise ValueError('Additional source versions require review')
    active = db.query(PromptTemplate).filter_by(template_type=revision['template_type'], is_active=True).one()
    if (active.id, active.version) != (revision['expected_active_id'], revision['expected_active_version']):
        raise ValueError('Active evaluator changed after review')
    next_version = (db.query(func.max(PromptTemplate.version)).filter_by(
        template_type=revision['template_type']).scalar() or 0) + 1
    if not apply:
        return dict(status='preview', id=source.id, version=next_version, is_active=False)
    source.template_type = revision['template_type']
    source.version = next_version
    source.is_active = False
    source.description = revision['description']
    db.commit()
    return dict(status='applied', id=source.id, version=source.version, is_active=source.is_active)


def register(db, revision, apply=False):
    if apply and db.bind.dialect.name == 'postgresql':
        db.execute(text("SET LOCAL lock_timeout = '10s'"))
        db.execute(text('LOCK TABLE prompt_templates IN EXCLUSIVE MODE'))
    if revision.get('action') == 'merge_template_type':
        return merge_template_type(db, revision, apply)
    active = db.query(PromptTemplate).filter_by(
        template_type=revision['template_type'], is_active=True).all()
    if len(active) != 1:
        raise ValueError('Expected exactly one active template')
    current = active[0]
    if (current.prompt_text, current.message_text) == (revision['prompt_text'], revision['message_text']):
        db.rollback()
        return dict(status='already_applied', version=current.version)
    if (current.version, current.prompt_text, current.message_text) != (
            revision['expected_version'], revision['expected_prompt_text'], revision['expected_message_text']):
        raise ValueError('Active template differs from reviewed source; refusing to overwrite')
    if not apply:
        return dict(status='preview', template_type=current.template_type,
                    source_version=current.version, action='create and activate new version')
    new = PromptTemplateService(db).create_template(
        revision['template_type'], revision['prompt_text'], revision['message_text'], revision['description'])
    return dict(status='applied', template_type=new.template_type, id=new.id, version=new.version)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('revision', type=Path)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    load_dotenv(Path(__file__).resolve().parents[1] / '.env')
    revision = json.loads(args.revision.read_text(encoding='utf-8'))
    try:
        engine = create_engine(os.environ['DATABASE_URL'], connect_args={'connect_timeout': 15})
        with Session(engine) as db:
            print(json.dumps(register(db, revision, args.apply), ensure_ascii=False))
    except Exception as exc:
        print('Registration failed: ' + type(exc).__name__)
        raise SystemExit(1)
