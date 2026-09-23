import json

from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_session import Session
from flask_migrate import Migrate  # type: ignore
from pymongo import MongoClient
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from .config import Config

db = SQLAlchemy()
migrate = Migrate()
sess = Session()


def _get_mongo_collection():
    try:
        mongo_client = MongoClient('mongodb://localhost:27017/', serverSelectionTimeoutMS=500)
        mongo_client.admin.command('ping')
        mongodb = mongo_client['applications']
        return mongodb['applications']
    except Exception:
        return None


applications_collection = _get_mongo_collection()


def _add_missing_column(table_name, column_name, column_sql):
    inspector = db.inspect(db.engine)
    if table_name not in set(inspector.get_table_names()):
        return
    existing_columns = {col['name'] for col in inspector.get_columns(table_name)}
    if column_name in existing_columns:
        return
    try:
        db.session.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_sql}"))
    except OperationalError as exc:
        db.session.rollback()
        if 'duplicate column name' not in str(exc).lower():
            raise


def ensure_db_schema():
    inspector = db.inspect(db.engine)
    tables = set(inspector.get_table_names())

    if 'user' in tables:
        user_columns = {col['name'] for col in inspector.get_columns('user')}
        if 'role' not in user_columns:
            _add_missing_column('user', 'role', "role VARCHAR(20)")
            db.session.execute(text("UPDATE user SET role = 'recruiter' WHERE role IS NULL"))
        if 'bio' not in user_columns:
            _add_missing_column('user', 'bio', 'bio TEXT')
        if 'skills' not in user_columns:
            _add_missing_column('user', 'skills', 'skills TEXT')
        if 'education' not in user_columns:
            _add_missing_column('user', 'education', 'education TEXT')
        if 'created_at' not in user_columns:
            _add_missing_column('user', 'created_at', 'created_at DATETIME')
            db.session.execute(text("UPDATE user SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL"))
        if 'is_active' not in user_columns:
            _add_missing_column('user', 'is_active', 'is_active BOOLEAN')
            db.session.execute(text("UPDATE user SET is_active = 1 WHERE is_active IS NULL"))

    if 'job' in tables:
        job_columns = {col['name'] for col in inspector.get_columns('job')}
        if 'job_type' not in job_columns:
            _add_missing_column('job', 'job_type', "job_type VARCHAR(50)")
            db.session.execute(text("UPDATE job SET job_type = 'Full-time' WHERE job_type IS NULL"))
        if 'job_role' not in job_columns:
            _add_missing_column('job', 'job_role', "job_role VARCHAR(50)")
            db.session.execute(text("UPDATE job SET job_role = 'General' WHERE job_role IS NULL"))
        if 'is_open' not in job_columns:
            _add_missing_column('job', 'is_open', 'is_open BOOLEAN')
            db.session.execute(text("UPDATE job SET is_open = 1 WHERE is_open IS NULL"))

    if 'application' in tables:
        app_columns = {col['name'] for col in inspector.get_columns('application')}
        if 'resume_id' not in app_columns:
            _add_missing_column('application', 'resume_id', 'resume_id INTEGER')
        if 'cover_note' not in app_columns:
            _add_missing_column('application', 'cover_note', 'cover_note TEXT')
        if 'ai_score' not in app_columns:
            _add_missing_column('application', 'ai_score', 'ai_score FLOAT')
            db.session.execute(text("UPDATE application SET ai_score = 0.0 WHERE ai_score IS NULL"))
        if 'submitted_resume' not in app_columns:
            _add_missing_column('application', 'submitted_resume', 'submitted_resume VARCHAR(255)')
        if 'status_history' not in app_columns:
            _add_missing_column('application', 'status_history', 'status_history TEXT')
        if 'recruiter_notes' not in app_columns:
            _add_missing_column('application', 'recruiter_notes', 'recruiter_notes TEXT')
        if 'recruiter_notes_visible' not in app_columns:
            _add_missing_column('application', 'recruiter_notes_visible', 'recruiter_notes_visible BOOLEAN')
            db.session.execute(text("UPDATE application SET recruiter_notes_visible = 0 WHERE recruiter_notes_visible IS NULL"))
        if 'interview_access' not in app_columns:
            _add_missing_column('application', 'interview_access', 'interview_access VARCHAR(20)')
            db.session.execute(text("UPDATE application SET interview_access = 'pending' WHERE interview_access IS NULL"))

    if 'interview' in tables:
        interview_columns = {col['name'] for col in inspector.get_columns('interview')}
        if 'notes_visible' not in interview_columns:
            _add_missing_column('interview', 'notes_visible', 'notes_visible BOOLEAN')
            db.session.execute(text("UPDATE interview SET notes_visible = 0 WHERE notes_visible IS NULL"))
        for column_name, column_sql in {
            'question_set_id': 'question_set_id INTEGER',
            'interviewer_names': 'interviewer_names VARCHAR(500)',
            'scheduled_timezone': 'scheduled_timezone VARCHAR(80)',
            'access_granted_at': 'access_granted_at DATETIME',
            'started_at': 'started_at DATETIME',
            'completed_at': 'completed_at DATETIME',
            'responses': 'responses TEXT',
            'ai_scores': 'ai_scores TEXT',
            'overall_score': 'overall_score FLOAT',
        }.items():
            if column_name not in interview_columns:
                _add_missing_column('interview', column_name, column_sql)

    db.session.commit()


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    app.jinja_env.filters['from_json'] = json.loads

    db.init_app(app)  
    migrate.init_app(app, db)
    sess.init_app(app)

    with app.app_context():
        from . import models
        db.create_all()
        ensure_db_schema()
        from .routes import main as main_blueprint
        app.register_blueprint(main_blueprint)

        return app
