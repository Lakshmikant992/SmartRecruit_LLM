from datetime import datetime, timedelta
import json

from app import create_app, db
from app.models import Application, Job, User

app = create_app()

with app.app_context():
    student = User.query.filter_by(email='student@example.com').first()
    recruiter = User.query.filter_by(role='recruiter').first()
    if student is None or recruiter is None:
        raise SystemExit('Create a student account and recruiter account before seeding applications.')

    samples = [
        ('Application Developer', 'Ongoing', 0, 0.88),
        ('Data Analyst', 'Completed', 14, 0.76),
        ('UX Designer', 'Applied', 30, 0.68),
        ('Cloud Engineer', 'Rejected', 45, 0.42),
        ('Product Analyst', 'Offered', 60, 0.91),
    ]
    created = 0
    for title, status, days_ago, score in samples:
        marker = f'[seed:student-applications:{title}]'
        job = Job.query.filter_by(description=marker, user_id=recruiter.id).first()
        if job is None:
            job = Job(
                title=title,
                location='Remote',
                experience='Entry level',
                job_type='Full-time',
                job_role=title,
                description=marker + f'\nBuild and support {title.lower()} projects. Requirements: communication, problem solving, technical skills.',
                salary='Competitive',
                user_id=recruiter.id,
            )
            db.session.add(job)
            db.session.flush()
        application = Application.query.filter_by(user_id=student.id, job_id=job.id).first()
        if application is None:
            applied_at = datetime.utcnow() - timedelta(days=days_ago)
            application = Application(
                user_id=student.id,
                job_id=job.id,
                message=str(score),
                ai_score=score,
                timestamp=applied_at,
                status=status,
                status_history=json.dumps([{'status': 'Applied', 'timestamp': applied_at.isoformat()}, {'status': status, 'timestamp': applied_at.isoformat()}]),
                cover_note='Seed application for dashboard verification.',
            )
            db.session.add(application)
            created += 1
    db.session.commit()
    print(f'Created {created} student application records.')
