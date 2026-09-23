from flask import Blueprint, render_template, redirect, url_for, flash, request, session, g, current_app, abort, jsonify, send_from_directory
from markdown import markdown
from werkzeug.utils import secure_filename
from datetime import datetime, timedelta, timezone
from functools import wraps
from email.message import EmailMessage
import smtplib
import os
import re
import pdfplumber  # type: ignore
import logging
import time
import json

from . import db, applications_collection
from .models import User, Job, Application, Interview, InterviewFeedback, InterviewQuestionSet
from .utils import allowed_file, evaluate_cv, extract_score, generate_interview_questions, generate_feedback, convert_keys_to_strings, extract_resume_text, rank_resume_comparison, evaluate_interview_response

main = Blueprint('main', __name__)


def mongo_safe_find_one(query):
    if applications_collection is None:
        return None
    return applications_collection.find_one(query)


def mongo_safe_insert(data):
    if applications_collection is None:
        return False
    applications_collection.insert_one(data)
    return True

INTERVIEW_STATUSES = {'Scheduled', 'Completed', 'Cancelled', 'Rescheduled', 'No Show'}
INTERVIEW_DECISIONS = {'Selected', 'Rejected', 'On Hold', 'Next Round'}
AI_INTERVIEW_STATUSES = {'Invited', 'In Progress', 'Completed', 'Revoked'}
APPLICATION_STATUSES = {'Applied', 'Under Review', 'Interview', 'Offered', 'Rejected', 'Withdrawn'}

JOB_JUNK_TERMS = {'ai', 'jbfvdgj jd'}


def _clean_job_value(value, fallback='Not specified'):
    value = re.sub(r'\[seed:\s*[^\]]+\]', '', str(value or ''), flags=re.IGNORECASE).strip()
    return value if value.lower() not in JOB_JUNK_TERMS and value else fallback


def _format_salary(value):
    raw = _clean_job_value(value, '')
    if not raw:
        return 'Not specified'
    numbers = re.findall(r'\d+(?:\.\d+)?', raw.replace(',', ''))
    if not numbers:
        return 'Not specified'
    formatted = [f'₹{float(number):,.0f}' for number in numbers[:2]]
    return f'{formatted[0]} – {formatted[1]} / year' if len(formatted) > 1 else f'{formatted[0]} / year'


def _valid_job_posting(title, location, experience, description, salary, job_role):
    values = (title, location, experience, description, salary, job_role)
    if any(not value for value in values) or len(title) < 3 or len(description) < 40:
        return False
    if any(term in ' '.join(values).lower() for term in JOB_JUNK_TERMS) or re.search(r'\[seed:', ' '.join(values), re.IGNORECASE):
        return False
    return bool(re.search(r'\d', salary))


@main.app_template_filter('job_salary')
def job_salary(value):
    return _format_salary(value)


@main.app_template_filter('clean_job')
def clean_job(value):
    return _clean_job_value(value)


@main.app_template_filter('time_ago')
def time_ago(value):
    if not value:
        return 'Recently'
    days = max(0, (datetime.utcnow() - value).days)
    return 'Today' if days == 0 else f'{days} day{"s" if days != 1 else ""} ago'


def _status_history(application):
    try:
        history = json.loads(application.status_history or '[]')
    except (TypeError, ValueError):
        history = []
    if not isinstance(history, list):
        history = []
    if not history:
        history = [{'status': 'Applied', 'timestamp': (application.timestamp or datetime.utcnow()).isoformat()}]
    return history


def _interview_access_value(application):
    return (getattr(application, 'interview_access', None) or 'pending').strip().lower()


def _set_application_status(application, status):
    status = 'Offered' if status == 'Accepted' else status
    if status not in APPLICATION_STATUSES:
        return
    application.status = status
    history = _status_history(application)
    if not history or history[-1].get('status') != status:
        history.append({'status': status, 'timestamp': datetime.utcnow().isoformat()})
    application.status_history = json.dumps(history)


def _question_list(raw_questions):
    if isinstance(raw_questions, list):
        return [str(item).strip() for item in raw_questions if str(item).strip()]
    questions = []
    for line in str(raw_questions or '').splitlines():
        cleaned = re.sub(r'^\s*(?:\d+|[-*])(?:[.)-])?\s*', '', line).strip()
        if cleaned and len(cleaned) > 12:
            questions.append(cleaned)
    return questions[:10]


def _scheduled_utc(date_value, time_value, offset_minutes):
    local = datetime.strptime(f'{date_value} {time_value}', '%Y-%m-%d %H:%M')
    offset = int(offset_minutes or 0)
    return local.replace(tzinfo=timezone(timedelta(minutes=-offset))).astimezone(timezone.utc).replace(tzinfo=None)


def _ai_interview_question_set(job):
    generated = generate_interview_questions(job.description, job.description, max_retries=2)
    questions = _question_list(generated)
    if len(questions) < 5:
        questions = [
            f'Which technical skills from this {job.title} role have you used in a real project?',
            'Walk through a difficult technical problem you solved and how you validated the solution.',
            'How would you test and monitor a change in this role\'s technology stack?',
            'Describe a trade-off you made between delivery speed, reliability, and maintainability.',
            'Tell us about a time you explained a technical decision to a non-technical stakeholder.',
        ]
    return questions[:10]


def _is_tech_job(job):
    text = ' '.join((job.title, job.job_role or '', job.description or '')).lower()
    return any(term in text for term in ('software', 'developer', 'engineer', 'data', 'devops', 'cloud', 'qa', 'test', 'technical', 'program', 'machine learning', 'frontend', 'backend', 'full stack'))

def _interview_owner(interview):
    return interview.application.job.user_id == g.user.id

def _notify_interview(interview, subject, body):
    mail_server = current_app.config.get('MAIL_SERVER')
    if not mail_server or not interview.application.user.email:
        return False
    message = EmailMessage()
    message['Subject'] = subject
    message['From'] = current_app.config.get('MAIL_FROM', 'no-reply@localhost')
    message['To'] = interview.application.user.email
    message.set_content(body)
    try:
        with smtplib.SMTP(mail_server, current_app.config.get('MAIL_PORT', 587), timeout=8) as smtp:
            if current_app.config.get('MAIL_USE_TLS', True):
                smtp.starttls()
            if current_app.config.get('MAIL_USERNAME'):
                smtp.login(current_app.config['MAIL_USERNAME'], current_app.config.get('MAIL_PASSWORD', ''))
            smtp.send_message(message)
        return True
    except (OSError, smtplib.SMTPException) as error:
        logging.warning('Interview email notification failed: %s', error)
        return False

def _parse_interview_payload(payload, existing=None):
    required = ('application_id', 'interviewer_id', 'interview_type', 'interview_round', 'date', 'time')
    if not all(str(payload.get(key, '')).strip() for key in required):
        raise ValueError('Candidate, interviewer, round, type, date, and time are required.')
    try:
        application_id = int(payload['application_id'])
        interviewer_id = int(payload['interviewer_id'])
        duration = int(payload.get('duration_minutes', 45))
        scheduled_at = datetime.strptime(f"{payload['date']} {payload['time']}", '%Y-%m-%d %H:%M')
    except (TypeError, ValueError):
        raise ValueError('Use a valid date, time, interviewer, and duration.')
    if duration not in {15, 30, 45, 60, 90, 120}:
        raise ValueError('Duration must be 15, 30, 45, 60, 90, or 120 minutes.')
    if scheduled_at < datetime.now() - timedelta(minutes=5) and not existing:
        raise ValueError('Interview time must be in the future.')
    return application_id, interviewer_id, scheduled_at, duration

@main.before_app_request
def load_user():
    user_id = session.get('user_id')
    if user_id:
        g.user = User.query.get(user_id)
    else:
        g.user = None

@main.context_processor
def inject_user():
    return {'user': g.user}


def role_required(*allowed_roles):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            if g.user is None:
                flash('You need to sign in first.', 'danger')
                return redirect(url_for('main.auth'))
            if allowed_roles and g.user.role not in allowed_roles:
                flash('You do not have access to this area.', 'danger')
                if g.user.role == 'student':
                    return redirect(url_for('main.student_jobs'))
                if g.user.role == 'recruiter':
                    return redirect(url_for('main.dashboard'))
                return redirect(url_for('main.admin_dashboard'))
            return func(*args, **kwargs)
        return wrapper
    return decorator

@main.route('/')
def home():
    if g.user is None:
        return redirect(url_for('main.auth'))
    if g.user.role == 'student':
        return redirect(url_for('main.student_jobs'))
    if g.user.role == 'admin':
        return redirect(url_for('main.admin_dashboard'))
    return redirect(url_for('main.dashboard'))

@main.route('/sign', methods=['GET', 'POST'])
def auth():
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'signup':
            first_name = request.form['first_name']
            last_name = request.form['last_name']
            role = request.form.get('role', 'recruiter').strip().lower() or 'recruiter'
            company_name = request.form.get('company_name', '').strip() or ('Student' if role == 'student' else 'Recruiter')
            email = request.form['email']
            phone_number = request.form['phone_number']
            birthday = request.form['birthday']
            password = request.form['password']
            confirm_password = request.form['confirm_password']

            # Validate password match
            if password != confirm_password:
                flash('Passwords do not match.', 'danger')
                return redirect(url_for('main.auth'))

            # Check if the email already exists
            existing_user = User.query.filter_by(email=email).first()
            if existing_user:
                flash('An account with this email already exists.', 'danger')
                return redirect(url_for('main.auth'))

            # Create a new user
            user = User(
                first_name=first_name,
                last_name=last_name,
                company_name=company_name,
                email=email,
                phone_number=phone_number,
                birthday=birthday,
                password=password,
                role=role
            )
            db.session.add(user)
            db.session.commit()
            flash('Signup successful! You can now sign in.', 'success')
            return redirect(url_for('main.auth'))

        elif action == 'signin':
            email = request.form['email']
            password = request.form['password']

            user = User.query.filter_by(email=email).first()
            if user and not user.is_active:
                flash('This account has been deactivated. Contact an administrator.', 'danger')
                return redirect(url_for('main.auth'))
            if user and user.password == password:
                session['user_id'] = user.id
                flash('Signin successful!', 'success')
                if getattr(user, 'role', 'recruiter') == 'student':
                    return redirect(url_for('main.student_jobs'))
                if getattr(user, 'role', 'recruiter') == 'admin':
                    return redirect(url_for('main.admin_dashboard'))
                return redirect(url_for('main.dashboard'))
            else:
                flash('Invalid email or password.', 'danger')
                return redirect(url_for('main.auth'))

    return render_template('sign.html')

@main.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out.', 'success')
    return redirect(url_for('main.auth'))

@main.route('/recruiter')
@role_required('recruiter')
def recruiter_dashboard():
    return redirect(url_for('main.dashboard'))

@main.route('/admin')
@role_required('admin')
def admin_dashboard():
    section = request.args.get('section', 'overview')
    search = request.args.get('search', '').strip()
    user_type = request.args.get('user_type', 'all')
    edit_user_id = request.args.get('edit_user_id', type=int)
    users_query = User.query
    if user_type in {'student', 'recruiter', 'admin'}:
        users_query = users_query.filter_by(role=user_type)
    if search:
        term = f'%{search}%'
        users_query = users_query.filter(db.or_(User.first_name.ilike(term), User.last_name.ilike(term), User.email.ilike(term)))
    users = users_query.order_by(User.created_at.desc()).all()
    jobs = Job.query.order_by(Job.date_posted.desc()).all()
    interviews = Interview.query.join(Application).join(Job).order_by(Interview.created_at.desc()).all()
    today = datetime.utcnow().date()
    applications = Application.query.all()
    completed_today = sum(1 for item in interviews if item.completed_at and item.completed_at.date() == today)
    pending_access = sum(1 for item in applications if _interview_access_value(item) == 'pending')
    pipeline = {
        'applications': len(applications),
        'screened': sum(1 for item in applications if item.ai_score and item.ai_score > 0),
        'interviews': sum(1 for item in interviews if item.status == 'Completed'),
    }
    return render_template('admin_dashboard.html', section=section, users=users, jobs=jobs, interviews=interviews,
                           recruiters=User.query.filter_by(role='recruiter', is_active=True).order_by(User.first_name).all(),
                           edit_user=User.query.get(edit_user_id) if edit_user_id else None,
                           total_candidates=User.query.filter_by(role='student').count(),
                           total_recruiters=User.query.filter_by(role='recruiter').count(),
                           active_jobs=Job.query.filter_by(is_open=True).count(),
                           completed_today=completed_today, pending_access=pending_access,
                           pipeline=pipeline, search=search, user_type=user_type)


def _admin_user_or_404(user_id):
    return User.query.get_or_404(user_id)


@main.route('/admin/users/save', methods=['POST'])
@role_required('admin')
def admin_save_user():
    user_id = request.form.get('user_id', '').strip()
    user = _admin_user_or_404(int(user_id)) if user_id else User()
    required = ('first_name', 'last_name', 'email', 'phone_number', 'birthday')
    if any(not request.form.get(field, '').strip() for field in required):
        flash('First name, last name, email, phone, and birthday are required.', 'danger')
        return redirect(url_for('main.admin_dashboard', section='users'))
    user.first_name = request.form['first_name'].strip()
    user.last_name = request.form['last_name'].strip()
    user.email = request.form['email'].strip()
    user.phone_number = request.form['phone_number'].strip()
    user.birthday = request.form['birthday'].strip()
    user.company_name = request.form.get('company_name', '').strip() or ('Student' if request.form.get('role') == 'student' else 'Recruiter')
    user.role = request.form.get('role', 'student').strip()
    user.password = request.form.get('password', '').strip() or getattr(user, 'password', 'changeme')
    user.is_active = True
    if not user_id:
        db.session.add(user)
    db.session.commit()
    flash('User saved successfully.', 'success')
    return redirect(url_for('main.admin_dashboard', section='users'))


@main.route('/admin/users/<int:user_id>/toggle', methods=['POST'])
@role_required('admin')
def admin_toggle_user(user_id):
    user = _admin_user_or_404(user_id)
    if user.id == g.user.id:
        flash('You cannot deactivate your own admin account.', 'warning')
    else:
        user.is_active = not user.is_active
        db.session.commit()
        flash(f"{user.first_name} {user.last_name} is now {'active' if user.is_active else 'deactivated'}.", 'success')
    return redirect(url_for('main.admin_dashboard', section='users'))


@main.route('/admin/users/<int:user_id>/role', methods=['POST'])
@role_required('admin')
def admin_update_role(user_id):
    user = _admin_user_or_404(user_id)
    role = request.form.get('role', '').strip().lower()
    if role not in {'student', 'recruiter', 'admin'}:
        flash('Invalid role selected.', 'danger')
    elif user.id == g.user.id and role != 'admin':
        flash('You cannot demote your own admin account.', 'warning')
    else:
        user.role = role
        db.session.commit()
        flash('User role updated.', 'success')
    return redirect(url_for('main.admin_dashboard', section='users'))


@main.route('/admin/users/<int:user_id>/delete', methods=['POST'])
@role_required('admin')
def admin_delete_user(user_id):
    user = _admin_user_or_404(user_id)
    if user.id == g.user.id:
        flash('You cannot delete your own admin account.', 'warning')
        return redirect(url_for('main.admin_dashboard', section='users'))
    Application.query.filter_by(user_id=user.id).delete(synchronize_session=False)
    Job.query.filter_by(user_id=user.id).delete(synchronize_session=False)
    db.session.delete(user)
    db.session.commit()
    flash('User and directly owned records deleted.', 'success')
    return redirect(url_for('main.admin_dashboard', section='users'))


@main.route('/admin/applications/<int:application_id>/access', methods=['POST'])
@role_required('admin')
def admin_application_access(application_id):
    application = Application.query.get_or_404(application_id)
    action = request.form.get('action', 'pending')
    application.interview_access = action if action in {'pending', 'granted', 'completed'} else 'pending'
    if action == 'reset':
        application.interview_access = 'pending'
        for interview in application.interviews:
            interview.status = 'Revoked'
            interview.completed_at = None
            interview.responses = None
            interview.ai_scores = None
            interview.overall_score = None
    db.session.commit()
    flash('Interview access updated.', 'success')
    return redirect(url_for('main.admin_dashboard', section='interviews'))


@main.route('/admin/applications/<int:application_id>/reassign', methods=['POST'])
@role_required('admin')
def admin_reassign_application(application_id):
    application = Application.query.get_or_404(application_id)
    job = Job.query.get_or_404(int(request.form.get('job_id')))
    recruiter = User.query.filter_by(id=int(request.form.get('recruiter_id')), role='recruiter').first_or_404()
    application.job_id = job.id
    for interview in application.interviews:
        interview.interviewer_id = recruiter.id
    db.session.commit()
    flash('Candidate assignment updated.', 'success')
    return redirect(url_for('main.admin_dashboard', section='interviews'))


@main.route('/admin/jobs/<int:job_id>/action', methods=['POST'])
@role_required('admin')
def admin_job_action(job_id):
    job = Job.query.get_or_404(job_id)
    action = request.form.get('action')
    if action == 'toggle':
        job.is_open = not job.is_open
    elif action == 'delete':
        Application.query.filter_by(job_id=job.id).delete(synchronize_session=False)
        db.session.delete(job)
    elif action == 'edit':
        job.title = request.form.get('title', job.title).strip() or job.title
        job.location = request.form.get('location', job.location).strip() or job.location
        job.description = request.form.get('description', job.description).strip() or job.description
        job.salary = request.form.get('salary', job.salary).strip() or job.salary
    db.session.commit()
    flash('Job updated successfully.', 'success')
    return redirect(url_for('main.admin_dashboard', section='jobs'))

@main.route('/student')
@role_required('student')
def student_dashboard():
    applications = Application.query.join(Job).filter(Application.user_id == g.user.id).order_by(Application.timestamp.desc()).all()
    jobs = Job.query.filter_by(is_open=True).order_by(Job.date_posted.desc()).limit(3).all()
    counts = {status: sum(1 for item in applications if item.status == status) for status in ('Applied', 'Shortlisted', 'Interview', 'Rejected')}
    profile_values = (g.user.bio, g.user.skills, g.user.education, g.user.cv_file, g.user.profile_photo)
    completeness = round(sum(bool(value) for value in profile_values) / len(profile_values) * 100)
    return render_template('student_dashboard.html', applications=applications[:5], recommended_jobs=jobs, counts=counts, completeness=completeness)

@main.route('/student/jobs')
@role_required('student')
def student_jobs():
    query = Job.query.filter_by(is_open=True)
    search_term = request.args.get('search', '').strip()
    role_filter = request.args.get('role', '').strip()
    location_filter = request.args.get('location', '').strip()
    type_filter = request.args.get('job_type', '').strip()
    experience_filter = request.args.get('experience', '').strip()
    posted_filter = request.args.get('posted', '').strip()
    salary_min = request.args.get('salary_min', type=float)
    salary_max = request.args.get('salary_max', type=float)

    if search_term:
        query = query.filter(db.or_(Job.title.ilike(f'%{search_term}%'), Job.description.ilike(f'%{search_term}%')))
    if role_filter:
        query = query.filter(Job.job_role.ilike(f'%{role_filter}%'))
    if location_filter:
        query = query.filter(Job.location.ilike(f'%{location_filter}%'))
    if type_filter:
        query = query.filter(Job.job_type.ilike(f'%{type_filter}%'))
    if experience_filter:
        query = query.filter(Job.experience.ilike(f'%{experience_filter}%'))
    if posted_filter:
        cutoff = datetime.utcnow() - timedelta(days=int(posted_filter))
        query = query.filter(Job.date_posted >= cutoff)

    sort = request.args.get('sort', 'newest').strip()
    jobs = query.order_by(Job.salary.desc(), Job.date_posted.desc()).all() if sort == 'salary' else query.order_by(Job.date_posted.desc()).all()
    if salary_min is not None or salary_max is not None:
        def salary_matches(job):
            numbers = [float(number) for number in re.findall(r'\d+(?:\.\d+)?', job.salary or '')]
            return numbers and (salary_min is None or max(numbers) >= salary_min) and (salary_max is None or min(numbers) <= salary_max)
        jobs = [job for job in jobs if salary_matches(job)]
    applied_job_ids = {item.job_id for item in Application.query.filter_by(user_id=g.user.id).all()}
    return render_template('student_jobs.html', jobs=jobs, filters=request.args, applied_job_ids=applied_job_ids, result_count=len(jobs))

@main.route('/student/job/<int:job_id>')
@role_required('student')
def student_job_detail(job_id):
    job = Job.query.get_or_404(job_id)
    return render_template('student_job_detail.html', job=job)

@main.route('/student/apply/<int:job_id>', methods=['GET', 'POST'])
@role_required('student')
def student_apply(job_id):
    job = Job.query.get_or_404(job_id)
    if request.method == 'POST':
        resume_file = request.files.get('resume')
        cover_note = request.form.get('cover_note', '').strip()

        if resume_file and resume_file.filename:
            extension = os.path.splitext(resume_file.filename)[1].lower()
            if extension not in {'.pdf', '.txt', '.doc', '.docx'}:
                flash('Please upload a PDF, DOC, DOCX, or TXT resume.', 'danger')
                return redirect(url_for('main.student_apply', job_id=job.id))
            filename = secure_filename(resume_file.filename)
            upload_dir = os.path.join(current_app.config['UPLOAD_FOLDER_CV'])
            os.makedirs(upload_dir, exist_ok=True)
            resume_path = os.path.join(upload_dir, f"student_{g.user.id}_{int(time.time())}_{filename}")
            resume_file.save(resume_path)
            resume_text = extract_resume_text(resume_path)
        else:
            if not g.user.cv_file:
                flash('Please upload or select a resume before applying.', 'danger')
                return redirect(url_for('main.student_apply', job_id=job.id))
            resume_path = os.path.join(current_app.config['UPLOAD_FOLDER_CV'], g.user.cv_file)
            if not os.path.isfile(resume_path):
                flash('Saved resume not found. Please upload again.', 'danger')
                return redirect(url_for('main.student_apply', job_id=job.id))
            resume_text = extract_resume_text(resume_path)

        submitted_resume = os.path.basename(resume_path)

        match, ai_score = evaluate_cv(resume_text, job.description)
        if not match:
            flash(f'Your profile is not a strong match yet. AI score: {ai_score:.2f}', 'warning')

        existing = Application.query.filter_by(user_id=g.user.id, job_id=job.id).first()
        if existing:
            flash('You have already applied for this job.', 'info')
            return redirect(url_for('main.student_applications'))

        application = Application(
            user_id=g.user.id,
            job_id=job.id,
            cover_note=cover_note or '',
            submitted_resume=submitted_resume,
            ai_score=float(ai_score),
            message=str(ai_score),
            status='Applied',
            status_history=json.dumps([{'status': 'Applied', 'timestamp': datetime.utcnow().isoformat()}])
        )
        db.session.add(application)
        db.session.commit()

        mongo_safe_insert({
            'application_id': str(application.id),
            'user_id': str(g.user.id),
            'job_id': str(job.id),
            'status': application.status,
            'ai_score': float(ai_score),
            'cover_note': cover_note,
            'feedback': [{'score': round(float(ai_score), 2), 'question': 'AI resume screening', 'response': 'Automated screening result'}]
        })

        flash('Application submitted successfully! Your recruiter can now view the AI match score.', 'success')
        return redirect(url_for('main.student_applications'))

    return render_template('student_apply.html', job=job)

@main.route('/student/applications')
@role_required('student')
def student_applications():
    query = Application.query.join(Job).filter(Application.user_id == g.user.id)
    status_filter = request.args.get('status', '').strip()
    if status_filter in APPLICATION_STATUSES:
        if status_filter == 'Offered':
            query = query.filter(db.or_(Application.status == 'Offered', Application.status == 'Accepted'))
        elif status_filter == 'Under Review':
            query = query.filter(db.or_(Application.status == 'Under Review', Application.status == 'Pending'))
        else:
            query = query.filter(Application.status == status_filter)
    sort = request.args.get('sort', 'date')
    if sort == 'score':
        query = query.order_by(Application.ai_score.desc(), Application.timestamp.desc())
    elif sort == 'status':
        query = query.order_by(Application.status.asc(), Application.timestamp.desc())
    else:
        sort = 'date'
        query = query.order_by(Application.timestamp.desc())
    applications = query.all()
    return render_template('student_applications.html', applications=applications, status_options=sorted(APPLICATION_STATUSES), selected_status=status_filter, selected_sort=sort)

@main.route('/student/application/<int:application_id>')
@role_required('student')
def student_application_detail(application_id):
    application = Application.query.get_or_404(application_id)
    if application.user_id != g.user.id:
        abort(403)
    application_data = mongo_safe_find_one({'application_id': str(application_id)})
    interviews = Interview.query.filter_by(application_id=application.id).order_by(Interview.scheduled_at.asc()).all()
    interview_access = _interview_access_value(application)
    interview_status = 'Not Started'
    if interview_access == 'granted':
        interview_status = 'Granted'
    elif interview_access == 'completed':
        interview_status = 'Completed'
    return render_template('student_application_detail.html', application=application, application_data=application_data, interviews=interviews, status_history=_status_history(application), interview_access=interview_access, interview_status=interview_status)


@main.route('/student/application/<int:application_id>/withdraw', methods=['POST'])
@role_required('student')
def student_withdraw_application(application_id):
    application = Application.query.get_or_404(application_id)
    if application.user_id != g.user.id:
        abort(403)
    if application.status not in {'Rejected', 'Offered', 'Withdrawn'}:
        _set_application_status(application, 'Withdrawn')
        db.session.commit()
        flash('Application withdrawn.', 'success')
    return redirect(url_for('main.student_applications'))


def _recruiter_application_or_404(application_id):
    application = Application.query.get_or_404(application_id)
    if application.job.user_id != g.user.id:
        abort(403)
    return application


def _comparison_record(application):
    filename = application.submitted_resume or application.user.cv_file
    resume_text = ''
    if filename:
        resume_path = os.path.join(current_app.config['UPLOAD_FOLDER_CV'], filename)
        if os.path.isfile(resume_path):
            try:
                resume_text = extract_resume_text(resume_path)
            except (OSError, ValueError):
                logging.warning('Could not read resume for application %s', application.id)
    feedback_data = mongo_safe_find_one({'application_id': str(application.id)}) or {}
    feedback_scores = [float(item.get('score', 0) or 0) for item in feedback_data.get('feedback', [])]
    score = application.ai_score or (sum(feedback_scores) / len(feedback_scores) / 10 if feedback_scores else 0)
    return {
        'application_id': application.id,
        'name': f'{application.user.first_name} {application.user.last_name}',
        'email': application.user.email,
        'applied_at': application.timestamp,
        'resume_filename': filename,
        'score': score,
        'feedback': feedback_data.get('feedback', []),
        'responses': feedback_data.get('responses', {}),
        'resume_text': resume_text,
        'interviews': application.interviews,
    }


@main.route('/recruiter/applications')
@role_required('recruiter')
def recruiter_applications(forced_job_id=None):
    jobs = Job.query.filter_by(user_id=g.user.id).order_by(Job.title.asc()).all()
    query = Application.query.join(Job).join(User, Application.user_id == User.id).filter(Job.user_id == g.user.id)
    job_id = forced_job_id or request.args.get('job_id', type=int)
    status = request.args.get('status', '').strip()
    search = request.args.get('search', '').strip()
    search = request.args.get('search', '').strip()
    min_score = request.args.get('min_score', type=float)
    date_from = request.args.get('date_from', '').strip()
    date_to = request.args.get('date_to', '').strip()
    sort = request.args.get('sort', 'date')
    if job_id:
        query = query.filter(Application.job_id == job_id)
    if status in APPLICATION_STATUSES or status in {'Pending', 'Accepted'}:
        query = query.filter(Application.status == status)
    if search:
        term = f'%{search}%'
        query = query.filter(db.or_(User.first_name.ilike(term), User.last_name.ilike(term), User.email.ilike(term)))
    if min_score is not None:
        query = query.filter(db.or_(
            db.and_(Application.ai_score <= 1, Application.ai_score >= min_score / 100),
            db.and_(Application.ai_score > 1, Application.ai_score >= min_score)
        ))
    try:
        if date_from:
            query = query.filter(Application.timestamp >= datetime.strptime(date_from, '%Y-%m-%d'))
        if date_to:
            query = query.filter(Application.timestamp < datetime.strptime(date_to, '%Y-%m-%d') + timedelta(days=1))
    except ValueError:
        flash('Use valid application dates.', 'warning')
    if sort == 'score':
        query = query.order_by(Application.ai_score.desc(), Application.timestamp.desc())
    elif sort == 'status':
        query = query.order_by(Application.status.asc(), Application.timestamp.desc())
    else:
        sort = 'date'
        query = query.order_by(Application.timestamp.desc())
    applications = query.all()
    breakdown = {item: sum(1 for application in applications if ('Offered' if application.status == 'Accepted' else ('Under Review' if application.status == 'Pending' else application.status)) == item) for item in ('Applied', 'Under Review', 'Interview', 'Offered', 'Rejected')}
    return render_template('recruiter_applications.html', applications=applications, jobs=jobs, selected_job=job_id, selected_status=status, selected_sort=sort, breakdown=breakdown)


@main.route('/recruiter/applications/<int:job_id>')
@role_required('recruiter')
def recruiter_applications_job(job_id):
    job = Job.query.get_or_404(job_id)
    if job.user_id != g.user.id:
        abort(403)
    return recruiter_applications(forced_job_id=job.id)


@main.route('/recruiter/applications/candidate/<int:application_id>')
@role_required('recruiter')
def recruiter_application_profile(application_id):
    application = _recruiter_application_or_404(application_id)
    record = _comparison_record(application)
    comparison = rank_resume_comparison([record], application.job.description)['candidates'][0]
    application_data = mongo_safe_find_one({'application_id': str(application.id)}) or {}
    ai_interview = next((item for item in application.interviews if item.question_set_id and item.responses), None)
    if ai_interview:
        application_data = dict(application_data)
        application_data['responses'] = json.loads(ai_interview.responses or '{}')
        scores = json.loads(ai_interview.ai_scores or '{}')
        application_data['feedback'] = [{'feedback': f'AI interview score: {scores.get(key, 0)}/10'} for key in application_data['responses']]
    return render_template('recruiter_candidate_profile.html', application=application, candidate=comparison, application_data=application_data, interviews=application.interviews, status_history=_status_history(application))


@main.route('/recruiter/application/<int:application_id>/grant-interview-access', methods=['POST'])
@role_required('recruiter')
def grant_interview_access(application_id):
    application = _recruiter_application_or_404(application_id)
    action = request.form.get('action', 'grant')
    if action == 'reset':
        application.interview_access = 'pending'
        if application.status == 'Interview':
            _set_application_status(application, 'Under Review')
        flash('Interview access reset for this candidate.', 'warning')
    else:
        application.interview_access = 'granted'
        if application.status in {'Applied', 'Under Review'}:
            _set_application_status(application, 'Interview')
        flash('Interview access granted. The candidate can now start the AI interview.', 'success')
    db.session.commit()
    return redirect(url_for('main.recruiter_application_profile', application_id=application.id))


@main.route('/recruiter/applications/<int:application_id>/update', methods=['POST'])
@role_required('recruiter')
def update_recruiter_application(application_id):
    application = _recruiter_application_or_404(application_id)
    status = request.form.get('status', '').strip()
    if status in APPLICATION_STATUSES:
        _set_application_status(application, status)
    application.recruiter_notes = request.form.get('recruiter_notes', '').strip()
    application.recruiter_notes_visible = request.form.get('recruiter_notes_visible') == 'on'
    db.session.commit()
    flash('Application profile updated.', 'success')
    return redirect(url_for('main.recruiter_application_profile', application_id=application.id))


@main.route('/student/application/<int:application_id>/resume')
@role_required('student')
def student_application_resume(application_id):
    application = Application.query.get_or_404(application_id)
    if application.user_id != g.user.id or not application.submitted_resume:
        abort(404)
    upload_dir = os.path.abspath(current_app.config['UPLOAD_FOLDER_CV'])
    if not os.path.isfile(os.path.join(upload_dir, application.submitted_resume)):
        abort(404)
    return send_from_directory(upload_dir, application.submitted_resume, as_attachment=False, download_name=application.submitted_resume)


@main.route('/recruiter/screening/application/<int:application_id>/resume')
@role_required('recruiter')
def recruiter_application_resume(application_id):
    application = Application.query.get_or_404(application_id)
    if application.job.user_id != g.user.id:
        abort(403)
    filename = application.submitted_resume or application.user.cv_file
    upload_dir = os.path.abspath(current_app.config['UPLOAD_FOLDER_CV'])
    if not filename or not os.path.isfile(os.path.join(upload_dir, filename)):
        abort(404)
    return send_from_directory(upload_dir, filename, as_attachment=False, download_name=filename)

@main.route('/student/interview/<int:application_id>', methods=['GET', 'POST'])
@role_required('student')
def student_interview(application_id):
    application = Application.query.get_or_404(application_id)
    if application.user_id != g.user.id:
        abort(403)

    if _interview_access_value(application) == 'pending':
        flash('Interview access not yet granted by the recruiter.', 'warning')
        return redirect(url_for('main.student_application_detail', application_id=application.id))

    interview = (Interview.query.filter(Interview.application_id == application.id)
                 .order_by(Interview.created_at.desc()).first())

    if interview is None:
        resume_path = os.path.join(current_app.config['UPLOAD_FOLDER_CV'], application.submitted_resume) if application.submitted_resume else None
        resume_text = ''
        if resume_path and os.path.exists(resume_path):
            try:
                resume_text = extract_resume_text(resume_path)
            except Exception as exc:
                logging.warning('Could not read resume for AI interview generation: %s', exc)
        job_description = application.job.description
        generated_questions = generate_interview_questions(resume_text or application.user.bio or application.user.skills or '', job_description, max_retries=2)
        cleaned_questions = []
        for item in generated_questions:
            if isinstance(item, str):
                q = item.strip().strip('-*• ')
                if q and q.endswith('?'):
                    cleaned_questions.append(q)
        if len(cleaned_questions) < 5:
            cleaned_questions = [
                'Describe a project where you solved a meaningful technical challenge and how you validated the outcome.',
                'How do you prioritize trade-offs between fast delivery, quality, and maintainability in a production environment?',
                'Tell us about a time you collaborated with cross-functional stakeholders to deliver a result.',
                'What technical skills from this role have you used most recently, and how did they impact your work?',
                'What would you do if a production issue appeared after deployment and the root cause was not immediately clear?'
            ]
        question_set = InterviewQuestionSet(job_id=application.job_id, questions=json.dumps(cleaned_questions[:8]), is_active=False)
        db.session.add(question_set)
        db.session.commit()
        interview = Interview(
            application_id=application.id,
            interviewer_id=application.job.user_id,
            interview_type='AI Interview',
            interview_round='Technical',
            scheduled_at=datetime.utcnow(),
            duration_minutes=30,
            question_set_id=question_set.id,
            status='In Progress',
            started_at=datetime.utcnow(),
            access_granted_at=datetime.utcnow(),
        )
        db.session.add(interview)
        db.session.commit()

    if _interview_access_value(application) == 'completed':
        return render_template('student_interview.html', application=application, interview=interview, questions=json.loads(interview.question_set.questions) if interview.question_set else [], locked=True, responses=json.loads(interview.responses or '{}'), completed=True)

    if request.method == 'POST':
        questions = json.loads(interview.question_set.questions) if interview.question_set else []
        current_index = int(request.form.get('question_index', 0))
        submitted_answer = request.form.get('answer', '').strip()
        existing_answers = json.loads(interview.responses or '{}') if interview.responses else {}

        if not submitted_answer:
            flash('Please provide a response before continuing.', 'warning')
            return render_template('student_interview.html', application=application, interview=interview, questions=questions, locked=False, responses=existing_answers, current_index=current_index, can_submit=False)

        existing_answers[str(current_index)] = submitted_answer
        interview.responses = json.dumps(existing_answers)
        interview.status = 'In Progress'
        interview.started_at = interview.started_at or datetime.utcnow()
        db.session.commit()

        if current_index + 1 < len(questions):
            return redirect(url_for('main.student_interview', application_id=application.id, question_index=current_index + 1))

        scores = {}
        evaluation_data = {}
        for idx, question in enumerate(questions):
            answer = existing_answers.get(str(idx), '').strip()
            if not answer:
                continue
            resume_text = ''
            if application.submitted_resume:
                resume_path = os.path.join(current_app.config['UPLOAD_FOLDER_CV'], application.submitted_resume)
                if os.path.exists(resume_path):
                    try:
                        resume_text = extract_resume_text(resume_path)
                    except Exception:
                        resume_text = ''
            result = evaluate_interview_response(question, answer, application.job.description, resume_text)
            scores[str(idx)] = result['score']
            evaluation_data[str(idx)] = {'question': question, 'answer': answer, 'score': result['score'], 'feedback': result['feedback']}

        interview.ai_scores = json.dumps(scores)
        interview.responses = json.dumps(existing_answers)
        interview.overall_score = round(sum(scores.values()) / len(scores), 1) if scores else 0
        interview.status = 'Completed'
        interview.completed_at = datetime.utcnow()
        interview.updated_at = datetime.utcnow()
        application.interview_access = 'completed'
        application.status = 'Under Review'
        db.session.commit()
        mongo_safe_insert({
            'application_id': str(application.id),
            'user_id': str(g.user.id),
            'job_id': str(application.job_id),
            'interview_status': 'completed',
            'responses': existing_answers,
            'scores': scores,
            'ai_feedback': evaluation_data,
            'overall_score': round(sum(scores.values()) / len(scores), 1) if scores else 0,
        })
        flash('AI interview completed successfully. Your recruiter can now review the score and transcript.', 'success')
        return redirect(url_for('main.student_interview', application_id=application.id))

    questions = json.loads(interview.question_set.questions) if interview.question_set else []
    responses = json.loads(interview.responses or '{}') if interview.responses else {}
    current_index = int(request.args.get('question_index', 0)) if request.args.get('question_index') else 0
    if current_index >= len(questions):
        current_index = max(0, len(questions) - 1)
    if interview.status == 'Completed':
        return render_template('student_interview.html', application=application, interview=interview, questions=questions, locked=True, responses=responses, current_index=0, completed=True)
    return render_template('student_interview.html', application=application, interview=interview, questions=questions, locked=False, responses=responses, current_index=current_index, can_submit=False)

@main.route('/student/profile', methods=['GET', 'POST'])
@role_required('student')
def student_profile():
    if request.method == 'POST':
        g.user.first_name = request.form.get('first_name', g.user.first_name)
        g.user.last_name = request.form.get('last_name', g.user.last_name)
        g.user.bio = request.form.get('bio', g.user.bio)
        g.user.skills = request.form.get('skills', g.user.skills)
        g.user.education = request.form.get('education', g.user.education)
        resume = request.files.get('resume')
        profile_photo = request.files.get('profile_photo')
        if resume and resume.filename:
            allowed = {'.pdf', '.txt', '.doc', '.docx'}
            ext = os.path.splitext(resume.filename)[1].lower()
            if ext not in allowed:
                flash('Resume must be PDF, DOC, DOCX, or TXT.', 'danger')
                return redirect(url_for('main.student_profile'))
            filename = secure_filename(resume.filename)
            upload_dir = os.path.join(current_app.config['UPLOAD_FOLDER_CV'])
            os.makedirs(upload_dir, exist_ok=True)
            saved_path = os.path.join(upload_dir, f"profile_{g.user.id}_{int(time.time())}_{filename}")
            resume.save(saved_path)
            g.user.cv_file = os.path.basename(saved_path)
        if profile_photo and profile_photo.filename:
            ext = os.path.splitext(profile_photo.filename)[1].lower()
            if ext not in {'.png', '.jpg', '.jpeg', '.webp'}:
                flash('Profile photo must be PNG, JPG, JPEG, or WEBP.', 'danger')
                return redirect(url_for('main.student_profile'))
            photo_dir = os.path.join(current_app.static_folder, 'uploads', 'photos')
            os.makedirs(photo_dir, exist_ok=True)
            photo_name = secure_filename(f'profile_{g.user.id}_{int(time.time())}{ext}')
            profile_photo.save(os.path.join(photo_dir, photo_name))
            g.user.profile_photo = photo_name
        db.session.commit()
        flash('Profile updated successfully.', 'success')
        return redirect(url_for('main.student_profile'))

    return render_template('student_profile.html', user=g.user)

@main.route('/create_job', methods=['GET', 'POST'])
def create_job():
    if g.user is None:
        flash('You need to sign in first.', 'danger')
        return redirect(url_for('main.auth'))

    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        location = request.form.get('location', '').strip()
        experience = request.form.get('experience', '').strip()
        description = request.form.get('description', '').strip()
        salary = request.form.get('salary', '').strip()
        job_type = request.form.get('job_type', 'Full-time').strip()
        job_role = request.form.get('job_role', 'General').strip()
        if not _valid_job_posting(title, location, experience, description, salary, job_role):
            flash('Please provide a genuine job title, role, location, description, and valid salary.', 'danger')
            return redirect(url_for('main.create_job'))

        new_job = Job(
            title=title,
            location=location,
            experience=experience,
            description=description,
            salary=salary,
            job_type=job_type or 'Full-time',
            job_role=job_role or 'General',
            user_id=g.user.id
        )
        db.session.add(new_job)
        db.session.commit()
        flash('Job created successfully!', 'success')
        return redirect(url_for('main.my_jobs'))

    return render_template('create_job.html')

@main.route('/my_jobs')
def my_jobs():
    if g.user is None:
        flash('You need to sign in first.', 'danger')
        return redirect(url_for('main.auth'))

    jobs = Job.query.filter_by(user_id=g.user.id).all()
    return render_template('my_jobs.html', jobs=jobs)

@main.route('/edit_job/<int:job_id>', methods=['GET', 'POST'])
def edit_job(job_id):
    if g.user is None:
        flash('You need to sign in first.', 'danger')
        return redirect(url_for('main.auth'))

    job = Job.query.get_or_404(job_id)
    if job.user_id != g.user.id:
        abort(403)

    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        location = request.form.get('location', '').strip()
        experience = request.form.get('experience', '').strip()
        description = request.form.get('description', '').strip()
        salary = request.form.get('salary', '').strip()
        job_role = request.form.get('job_role', job.job_role or 'General').strip()
        if not _valid_job_posting(title, location, experience, description, salary, job_role):
            flash('Please provide a genuine job title, role, location, description, and valid salary.', 'danger')
            return redirect(url_for('main.edit_job', job_id=job.id))
        job.title, job.location, job.experience = title, location, experience
        job.description, job.salary, job.job_role = description, salary, job_role
        job.job_type = request.form.get('job_type', job.job_type or 'Full-time').strip() or 'Full-time'
        db.session.commit()
        flash('Job updated successfully!', 'success')
        return redirect(url_for('main.my_jobs'))

    return render_template('edit_job.html', job=job)

@main.route('/delete_job/<int:job_id>', methods=['POST'])
def delete_job(job_id):
    if g.user is None:
        flash('You need to sign in first.', 'danger')
        return redirect(url_for('main.auth'))

    job = Job.query.get_or_404(job_id)
    if job.user_id != g.user.id:
        abort(403)

    db.session.delete(job)
    db.session.commit()
    flash('Job deleted successfully!', 'success')
    return redirect(url_for('main.my_jobs'))

@main.route('/settings', methods=['GET', 'POST'])
def settings():
    if 'user_id' not in session:
        flash('You need to sign in first.', 'danger')
        return redirect(url_for('main.auth'))

    user = User.query.get(session['user_id'])
    
    if user is None:
        flash('User not found.', 'danger')
        return redirect(url_for('main.auth'))

    if request.method == 'POST':
        # Handle General Settings Form Submission
        if 'save_changes' in request.form:
            # Fetching and validating form data
            first_name = request.form.get('first_name')
            last_name = request.form.get('last_name')
            company_name = request.form.get('company_name')
            email = request.form.get('email')
            phone_number = request.form.get('phone_number')
            birthday = request.form.get('birthday')

            # Ensure no required fields are empty
            if not all([first_name, last_name, company_name, email, phone_number, birthday]):
                flash('All fields are required.', 'danger')
                return redirect(url_for('main.settings'))

            # Update user details
            user.first_name = first_name
            user.last_name = last_name
            user.company_name = company_name
            user.email = email
            user.phone_number = phone_number
            user.birthday = birthday

            # Handle Profile Photo Upload
            if 'profile_photo' in request.files:
                profile_photo = request.files['profile_photo']
                if profile_photo and allowed_file(profile_photo.filename, {'jpg', 'jpeg', 'png'}):
                    photo_filename = secure_filename(profile_photo.filename)
                    profile_photo.save(os.path.join(current_app.config['UPLOAD_FOLDER_PHOTOS'], photo_filename))
                    user.profile_photo = photo_filename

            # Commit changes to the database
            try:
                db.session.commit()
                flash('General settings updated successfully!', 'success')
            except Exception as e:
                db.session.rollback()
                logging.error(f"Error updating settings: {e}")
                flash('An error occurred while updating your settings. Please try again.', 'danger')

            return redirect(url_for('main.settings'))

        # Handle CV Upload Form Submission
        if 'upload_cv' in request.form:
            if 'cv_file' in request.files:
                cv_file = request.files['cv_file']
                if cv_file and allowed_file(cv_file.filename, {'pdf'}):
                    cv_filename = secure_filename(cv_file.filename)
                    cv_file.save(os.path.join(current_app.config['UPLOAD_FOLDER_CV'], cv_filename))
                    user.cv_file = cv_filename

            # Commit changes to the database
            try:
                db.session.commit()
                flash('CV uploaded successfully!', 'success')
            except Exception as e:
                db.session.rollback()
                logging.error(f"Error uploading CV: {e}")
                flash('An error occurred while uploading your CV. Please try again.', 'danger')

            return redirect(url_for('main.settings'))

    return render_template('settings.html', user=user)

@main.route('/job/<int:job_id>')
def job_detail(job_id):
    if g.user is None:
        flash('You need to sign in first.', 'danger')
        return redirect(url_for('main.auth'))

    job = Job.query.get_or_404(job_id)
    job.description = markdown(job.description)
    return render_template('job_detail.html', job=job)

@main.route('/apply/<int:job_id>', methods=['GET'])
def apply(job_id):
    if g.user is None:
        flash('You need to sign in first.', 'danger')
        return redirect(url_for('main.auth'))

    job = Job.query.get_or_404(job_id)

    existing_application_sqlite = Application.query.filter_by(user_id=g.user.id, job_id=job_id).first()
    existing_application_mongo = mongo_safe_find_one({
        'user_id': str(g.user.id),
        'job_id': str(job_id)
    })

    if existing_application_sqlite or existing_application_mongo:
        flash('You have already applied for this job.', 'alert')
        return redirect(url_for('main.job_detail', job_id=job_id))

    if not g.user.cv_file:
        flash('Please upload your CV in settings before applying.', 'danger')
        return redirect(url_for('main.settings'))

    cv_path = os.path.join(current_app.config['UPLOAD_FOLDER_CV'], g.user.cv_file)
    if not os.path.isfile(cv_path):
        flash('CV file not found. Please upload again.', 'danger')
        return redirect(url_for('main.settings'))

    try:
        with pdfplumber.open(cv_path) as pdf:
            text = ''.join(page.extract_text() for page in pdf.pages if page.extract_text())
    except Exception as e:
        logging.error(f"Failed to process CV: {e}")
        flash('Failed to process CV.', 'danger')
        return redirect(url_for('main.job_detail', job_id=job_id))

    match, similarity_score = evaluate_cv(text, job.description)
    if not match:
        flash(f'Your CV does not match the job requirements. Similarity score: {similarity_score:.2f}', 'error')
        return redirect(url_for('main.job_detail', job_id=job_id))

    questions = generate_interview_questions(text, job.description)
    session['questions'] = questions
    session['current_question'] = 0
    session['responses'] = {}
    session['job_id'] = job_id
    session['similarity_score'] = similarity_score

    return redirect(url_for('main.interview_questions'))

@main.route('/interview_questions', methods=['GET', 'POST'])
def interview_questions():
    if g.user is None:
        flash('You need to sign in first.', 'danger')
        return redirect(url_for('main.auth'))

    questions = session.get('questions')
    current_question = session.get('current_question', 0)
    responses = session.get('responses', {})

    if request.method == 'POST':
        response = request.form.get('response')
        if response:
            responses[str(current_question)] = response
            session['responses'] = responses
            current_question += 1
            session['current_question'] = current_question

            if current_question >= len(questions):
                return redirect(url_for('main.review_responses'))

    if current_question < len(questions):
        question = questions[current_question]
        return render_template('interview_questions.html', question_number=current_question + 1, question_text=question)
    else:
        return redirect(url_for('main.review_responses'))

@main.route('/review_responses')
def review_responses():
    if g.user is None:
        flash('You need to sign in first.', 'danger')
        return redirect(url_for('main.auth'))

    return render_template('loading.html', next_url = url_for('main.generate_feedbacks'))

@main.route('/generate_feedbacks')
def generate_feedbacks():
    if g.user is None:
        flash('You need to sign in first.', 'danger')
        return redirect(url_for('main.auth'))

    responses = session.get('responses', {})
    questions = session.get('questions', [])
    job_id = session.get('job_id')
    job = Job.query.get_or_404(job_id)
    similarity_score = session.get('similarity_score')

    feedback_list = []
    for idx, response in responses.items():
        question = questions[int(idx)]
        feedback = generate_feedback(question, response, job.description)
        score = extract_score(feedback)
        time.sleep(2)  
        feedback_list.append({
            'question': question,
            'response': response,
            'feedback': feedback,
            'score':score
        })

    new_application = Application(
        user_id=g.user.id,
        job_id=job_id,
        message=similarity_score,
        timestamp=datetime.utcnow(),
        status='Pending'
    )
    db.session.add(new_application)
    db.session.commit()

    application_data = {
        'application_id': str(new_application.id),
        'user_id': str(g.user.id),
        'job_id': str(job_id),
        'responses': convert_keys_to_strings(responses),
        'feedback': feedback_list
    }
    mongo_safe_insert(application_data)

    flash('Application submitted successfully!', 'success')
    return redirect(url_for('main.view_applications'))

@main.route('/view_applications')
def view_applications():
    if g.user is None:
        flash('You need to sign in first.', 'danger')
        return redirect(url_for('main.auth'))

    applications = (Application.query
                    .join(Job, Application.job_id == Job.id)
                    .filter(Application.user_id == g.user.id)
                    .order_by(Application.timestamp.desc())
                    .all())
    status_aliases = {'Pending': 'Under Review', 'Accepted': 'Offered'}
    applications_list = [{
        'id': application.id,
        'job_title': application.job.title,
        'application_date': application.timestamp.strftime('%b %d, %Y') if application.timestamp else 'N/A',
        'status': status_aliases.get(application.status, application.status)
    } for application in applications]

    return render_template('view_applications.html', applications=applications_list)

@main.route('/view_candidates/<int:job_id>')
def view_candidates(job_id):
    if g.user is None:
        flash('You need to sign in first.', 'danger')
        return redirect(url_for('main.auth'))

    job = Job.query.get_or_404(job_id)
    if job.user_id != g.user.id:
        abort(403)

    applications = Application.query.filter_by(job_id=job_id).all()
    candidates = []
    for app in applications:
        user = User.query.get(app.user_id)
        candidates.append({
            'application_id': app.id,
            'name': f"{user.first_name} {user.last_name}",
            'email': user.email,
            'phone': user.phone_number,
            'status': app.status,
            'applied_on': app.timestamp
        })

    return render_template('view_candidates.html', candidates=candidates, job=job)

@main.route('/view_interview/<int:application_id>')
def view_interview(application_id):
    if g.user is None:
        flash('You need to sign in first.', 'danger')
        return redirect(url_for('main.auth'))

    application = Application.query.get_or_404(application_id)
    job = Job.query.get(application.job_id)
    if job.user_id != g.user.id:
        abort(403)

    application_data = mongo_safe_find_one({'application_id': str(application_id)})
    if not application_data:
        flash('Interview data not found.', 'danger')
        return redirect(url_for('main.view_candidates', job_id=job.id))

    feedback_list = application_data.get('feedback', [])
    
    # Pass application_id to the template
    return render_template('view_interview.html', feedback_list=feedback_list, applicant=application.user, application_id=application_id)

@main.route('/accept_application/<int:application_id>', methods=['POST'])
def accept_application(application_id):
    if g.user is None:
        flash('You need to sign in first.', 'danger')
        return redirect(url_for('main.auth'))

    application = Application.query.get_or_404(application_id)
    job = Job.query.get(application.job_id)
    if job.user_id != g.user.id:
        abort(403)

    _set_application_status(application, 'Offered')
    db.session.commit()
    flash('Application accepted.', 'success')
    return redirect(url_for('main.view_candidates', job_id=job.id))

@main.route('/reject_application/<int:application_id>', methods=['POST'])
def reject_application(application_id):
    if g.user is None:
        flash('You need to sign in first.', 'danger')
        return redirect(url_for('main.auth'))

    application = Application.query.get_or_404(application_id)
    job = Job.query.get(application.job_id)
    if job.user_id != g.user.id:
        abort(403)

    _set_application_status(application, 'Rejected')
    db.session.commit()
    flash('Application rejected.', 'success')
    return redirect(url_for('main.view_candidates', job_id=job.id))

@main.route('/dashboard')
def dashboard():
    if g.user is None:
        flash('You need to sign in first.', 'danger')
        return redirect(url_for('main.auth'))

    jobs = Job.query.filter_by(user_id=g.user.id).all()
    return render_template('dashboard.html', jobs=jobs)

@main.route('/recruiter/interviews')
@role_required('recruiter')
def recruiter_interviews():
    return recruiter_interview_schedule()


@main.route('/recruiter/interviews/question-sets')
@role_required('recruiter')
def recruiter_interview_question_sets():
    jobs = [job for job in Job.query.filter_by(user_id=g.user.id).order_by(Job.title.asc()).all() if _is_tech_job(job)]
    return render_template('recruiter_ai_interviews.html', jobs=jobs, selected_job=None, question_set=None, question_set_questions=[], applications=[])


@main.route('/recruiter/interviews/results')
@role_required('recruiter')
def recruiter_interview_results():
    interviews = (Interview.query.join(Application).join(Job)
                  .filter(Job.user_id == g.user.id, Interview.status == 'Completed')
                  .order_by(Interview.completed_at.desc(), Interview.updated_at.desc()).all())
    return render_template('recruiter_interview_results.html', interviews=interviews)


@main.route('/recruiter/interviews/schedule')
@role_required('recruiter')
def recruiter_interview_schedule():
    jobs = Job.query.filter_by(user_id=g.user.id).order_by(Job.title.asc()).all()
    applicants = Application.query.join(Job).filter(Job.user_id == g.user.id).order_by(Application.timestamp.desc()).all()
    query = Interview.query.join(Application).join(Job).filter(Job.user_id == g.user.id)
    job_id = request.args.get('job_id', type=int)
    interview_type = request.args.get('interview_type', '').strip()
    status = request.args.get('status', '').strip()
    search = request.args.get('search', '').strip()
    date_from = request.args.get('date_from', '').strip()
    date_to = request.args.get('date_to', '').strip()
    if job_id:
        query = query.filter(Job.id == job_id)
    if interview_type in {'AI Interview', 'Live Interview'}:
        query = query.filter(Interview.interview_type == interview_type)
    if status in INTERVIEW_STATUSES | AI_INTERVIEW_STATUSES:
        query = query.filter(Interview.status == status)
    if search:
        term = f'%{search}%'
        query = query.join(User, Application.user_id == User.id).filter(db.or_(User.first_name.ilike(term), User.last_name.ilike(term)))
    try:
        if date_from:
            query = query.filter(Interview.scheduled_at >= datetime.strptime(date_from, '%Y-%m-%d'))
        if date_to:
            query = query.filter(Interview.scheduled_at < datetime.strptime(date_to, '%Y-%m-%d') + timedelta(days=1))
    except ValueError:
        flash('Use valid schedule dates.', 'warning')
    interviews = query.order_by(Interview.scheduled_at.asc()).all()
    now = datetime.utcnow()
    week_start = now - timedelta(days=now.weekday())
    week_end = week_start + timedelta(days=7)
    week_items = [item for item in interviews if week_start <= item.scheduled_at < week_end]
    stats = {
        'week': sum(item.status in {'Scheduled', 'Rescheduled'} for item in week_items),
        'month_completed': sum(item.status == 'Completed' and item.scheduled_at.year == now.year and item.scheduled_at.month == now.month for item in interviews),
        'today': 0,
        'completed': sum(item.status == 'Completed' for item in interviews),
        'cancelled': sum(item.status in {'Cancelled', 'No Show'} for item in interviews),
        'total': len(interviews),
    }
    today_items = [item for item in interviews if item.scheduled_at.date() == now.date()]
    stats['today'] = len(today_items)
    stats['cancel_rate'] = round((stats['cancelled'] / len(interviews)) * 100, 1) if interviews else 0
    completed_scores = [item.overall_score for item in interviews if item.status == 'Completed' and item.overall_score is not None]
    stats['avg_score'] = round(sum(completed_scores) / len(completed_scores), 1) if completed_scores else 0
    upcoming_items = [item for item in interviews if item.scheduled_at >= now and item.status in {'Scheduled', 'Rescheduled'}][:5]
    calendar_days = [now.date() + timedelta(days=offset - now.weekday()) for offset in range(14)]
    return render_template('recruiter_interview_schedule.html', jobs=jobs, applicants=applicants, interviews=interviews, today_items=today_items, upcoming_items=upcoming_items, stats=stats, selected_job=job_id, selected_type=interview_type, selected_status=status, calendar_days=calendar_days, today_date=now.date())


def _create_scheduled_interview(application, job, payload, question_set=None):
    interview_type = payload.get('interview_type', 'AI Interview').strip()
    if interview_type not in {'AI Interview', 'Live Interview'}:
        raise ValueError('Choose AI Interview or Live Interview.')
    if interview_type == 'Live Interview' and not payload.get('interviewer_names', '').strip():
        raise ValueError('An interviewer is required for live interviews.')
    try:
        scheduled_at = _scheduled_utc(payload.get('date', ''), payload.get('time', ''), payload.get('timezone_offset', '0'))
        duration = int(payload.get('duration_minutes', '30'))
    except (TypeError, ValueError):
        raise ValueError('Choose a valid future date, time, and duration.')
    if scheduled_at <= datetime.utcnow():
        raise ValueError('Interview date and time must be in the future.')
    if duration not in {15, 30, 45, 60}:
        raise ValueError('Duration must be 15, 30, 45, or 60 minutes.')
    duplicate = Interview.query.filter_by(application_id=application.id).filter(Interview.status.in_({'Scheduled', 'Rescheduled', 'In Progress'})).first()
    if duplicate:
        raise ValueError('This candidate already has an active interview for this job.')
    if interview_type == 'AI Interview' and question_set is None:
        raise ValueError('Save a finalized question set for this job first.')
    interview = Interview(application_id=application.id, interviewer_id=g.user.id, scheduled_at=scheduled_at, duration_minutes=duration, interview_type=interview_type, interview_round='Technical', question_set_id=question_set.id if question_set else None, meeting_link=payload.get('meeting_link', '').strip() or None, interviewer_names=payload.get('interviewer_names', '').strip() or None, notes=payload.get('notes', '').strip() or None, notes_visible=payload.get('notes_visible') == 'on', scheduled_timezone=payload.get('timezone_name', 'UTC'), status='Scheduled', access_granted_at=datetime.utcnow())
    db.session.add(interview)
    _set_application_status(application, 'Interview')
    db.session.commit()
    _notify_interview(interview, f'Interview scheduled: {job.title}', f'Your {interview_type} for {job.title} is scheduled for {scheduled_at:%B %d, %Y at %H:%M} UTC for {duration} minutes.' + (f' Meeting link: {interview.meeting_link}' if interview.meeting_link else ''))
    return interview


@main.route('/recruiter/interviews/schedule/create', methods=['POST'])
@role_required('recruiter')
def create_scheduled_interview():
    application = Application.query.get_or_404(request.form.get('application_id', type=int))
    if application.job.user_id != g.user.id:
        abort(403)
    question_set = InterviewQuestionSet.query.filter_by(job_id=application.job_id, is_active=True).order_by(InterviewQuestionSet.created_at.desc()).first()
    try:
        _create_scheduled_interview(application, application.job, request.form, question_set)
    except ValueError as error:
        flash(str(error), 'warning')
    else:
        flash('Interview scheduled and candidate notified.', 'success')
    return redirect(url_for('main.recruiter_interview_schedule'))


@main.route('/recruiter/interviews/<int:job_id>')
@role_required('recruiter')
def recruiter_interviews_job(job_id):
    job = Job.query.get_or_404(job_id)
    if job.user_id != g.user.id:
        abort(403)
    if not _is_tech_job(job):
        flash('AI Interviews are available for technology roles only.', 'warning')
        return redirect(url_for('main.recruiter_interviews'))
    question_set = InterviewQuestionSet.query.filter_by(job_id=job.id, is_active=True).order_by(InterviewQuestionSet.created_at.desc()).first()
    applications = Application.query.filter_by(job_id=job.id).order_by(Application.timestamp.desc()).all()
    interviews = {item.application_id: item for item in Interview.query.filter(Interview.application_id.in_([item.id for item in applications]), Interview.question_set_id.isnot(None)).all()} if applications else {}
    question_set_questions = _question_list(json.loads(question_set.questions)) if question_set else []
    return render_template('recruiter_ai_interviews.html', jobs=[item for item in Job.query.filter_by(user_id=g.user.id).order_by(Job.title.asc()).all() if _is_tech_job(item)], selected_job=job, question_set=question_set, question_set_questions=question_set_questions, applications=applications, interviews=interviews)


@main.route('/recruiter/interviews/<int:job_id>/schedule/<int:application_id>', methods=['POST'])
@role_required('recruiter')
def schedule_ai_interview(job_id, application_id):
    application = _recruiter_application_or_404(application_id)
    if application.job_id != job_id:
        abort(404)
    job = application.job
    question_set = InterviewQuestionSet.query.filter_by(job_id=job_id, is_active=True).order_by(InterviewQuestionSet.created_at.desc()).first()
    if question_set is None:
        flash('Save a finalized question set before scheduling an AI interview.', 'warning')
        return redirect(url_for('main.recruiter_interviews_job', job_id=job_id))
    interview_type = request.form.get('interview_type', 'AI Interview')
    if interview_type not in {'AI Interview', 'Live Interview'}:
        abort(400)
    try:
        scheduled_at = _scheduled_utc(request.form.get('date', ''), request.form.get('time', ''), request.form.get('timezone_offset', '0'))
        duration = int(request.form.get('duration_minutes', '30'))
    except (TypeError, ValueError):
        flash('Choose a valid date, time, and duration.', 'warning')
        return redirect(url_for('main.recruiter_interviews_job', job_id=job_id))
    if duration not in {15, 30, 45, 60}:
        abort(400)
    interview = (Interview.query.filter_by(application_id=application.id)
                 .filter(Interview.question_set_id.isnot(None))
                 .order_by(Interview.created_at.desc()).first())
    previous_status = interview.status if interview else None
    if interview is None:
        interview = Interview(application_id=application.id, interviewer_id=g.user.id, scheduled_at=scheduled_at, interview_round='Technical')
    interview.question_set_id = question_set.id
    interview.interview_type = interview_type
    interview.scheduled_at = scheduled_at
    interview.duration_minutes = duration
    interview.meeting_link = request.form.get('meeting_link', '').strip() or None
    interview.interviewer_names = request.form.get('interviewer_names', '').strip() or None
    interview.notes = request.form.get('notes', '').strip() or None
    interview.notes_visible = request.form.get('notes_visible') == 'on'
    interview.scheduled_timezone = request.form.get('timezone_name', 'UTC')
    interview.status = 'Rescheduled' if previous_status in {'Scheduled', 'Rescheduled'} else 'Scheduled'
    interview.access_granted_at = interview.access_granted_at or datetime.utcnow()
    db.session.add(interview)
    _set_application_status(application, 'Interview')
    db.session.commit()
    _notify_interview(interview, f'Interview scheduled: {job.title}', f'Your {interview_type} for {job.title} is scheduled for {scheduled_at:%B %d, %Y at %H:%M} UTC for {duration} minutes.' + (f' Meeting link: {interview.meeting_link}' if interview.meeting_link else ''))
    flash('Interview scheduled and candidate notified.', 'success')
    return redirect(url_for('main.recruiter_interviews_job', job_id=job_id))


@main.route('/recruiter/interviews/<int:job_id>/cancel/<int:application_id>', methods=['POST'])
@role_required('recruiter')
def cancel_ai_interview(job_id, application_id):
    application = _recruiter_application_or_404(application_id)
    if application.job_id != job_id:
        abort(404)
    interview = (Interview.query.filter_by(application_id=application.id)
                 .filter(Interview.question_set_id.isnot(None))
                 .order_by(Interview.created_at.desc()).first())
    if interview:
        interview.status = 'Cancelled'
        db.session.commit()
        _notify_interview(interview, f'Interview cancelled: {application.job.title}', f'Your interview for {application.job.title} has been cancelled.')
    return redirect(url_for('main.recruiter_interviews_job', job_id=job_id))


@main.route('/recruiter/interviews/<int:job_id>/start/<int:application_id>', methods=['POST'])
@role_required('recruiter')
def start_ai_interview(job_id, application_id):
    application = _recruiter_application_or_404(application_id)
    if application.job_id != job_id:
        abort(404)
    interview = (Interview.query.filter_by(application_id=application.id)
                 .filter(Interview.question_set_id.isnot(None))
                 .order_by(Interview.created_at.desc()).first())
    if interview is None or interview.status != 'Invited':
        abort(404)
    interview.status = 'In Progress'
    interview.started_at = datetime.utcnow()
    db.session.commit()
    return redirect(url_for('main.recruiter_interviews_job', job_id=job_id))


@main.route('/recruiter/interviews/<int:job_id>/generate', methods=['POST'])
@role_required('recruiter')
def generate_ai_interview_questions(job_id):
    job = Job.query.get_or_404(job_id)
    if job.user_id != g.user.id:
        abort(403)
    if not _is_tech_job(job):
        abort(400, description='AI Interviews are available for technology roles only.')
    questions = _ai_interview_question_set(job)
    question_set = InterviewQuestionSet(job_id=job.id, questions=json.dumps(questions), is_active=True)
    db.session.add(question_set)
    db.session.commit()
    flash('Questions generated. Review and save this set before inviting candidates.', 'success')
    return redirect(url_for('main.recruiter_interviews_job', job_id=job.id))


@main.route('/recruiter/interviews/<int:job_id>/save', methods=['POST'])
@role_required('recruiter')
def save_ai_interview_questions(job_id):
    job = Job.query.get_or_404(job_id)
    if job.user_id != g.user.id:
        abort(403)
    if not _is_tech_job(job):
        abort(400, description='AI Interviews are available for technology roles only.')
    questions = _question_list(request.form.getlist('questions'))
    if not 5 <= len(questions) <= 10:
        flash('Finalize between 5 and 10 questions.', 'warning')
        return redirect(url_for('main.recruiter_interviews_job', job_id=job.id))
    InterviewQuestionSet.query.filter_by(job_id=job.id, is_active=True).update({'is_active': False})
    question_set = InterviewQuestionSet(job_id=job.id, questions=json.dumps(questions), is_active=True)
    db.session.add(question_set)
    db.session.commit()
    flash('Question set saved.', 'success')
    return redirect(url_for('main.recruiter_interviews_job', job_id=job.id))


@main.route('/recruiter/interviews/<int:job_id>/invite', methods=['POST'])
@role_required('recruiter')
def invite_ai_interviews(job_id):
    job = Job.query.get_or_404(job_id)
    if job.user_id != g.user.id:
        abort(403)
    question_set = InterviewQuestionSet.query.filter_by(job_id=job.id, is_active=True).order_by(InterviewQuestionSet.created_at.desc()).first()
    if question_set is None:
        flash('Save a finalized question set before inviting candidates.', 'warning')
        return redirect(url_for('main.recruiter_interviews_job', job_id=job.id))
    application_ids = {int(value) for value in request.form.getlist('application_ids') if value.isdigit()}
    for application in Application.query.filter(Application.job_id == job.id, Application.id.in_(application_ids)).all():
        existing = Interview.query.filter_by(application_id=application.id, question_set_id=question_set.id).first()
        if existing and existing.status != 'Revoked':
            continue
        interview = existing or Interview(application_id=application.id, interviewer_id=g.user.id, scheduled_at=datetime.utcnow(), interview_type='AI', interview_round='Technical')
        interview.question_set_id = question_set.id
        interview.status = 'Invited'
        interview.access_granted_at = datetime.utcnow()
        interview.responses = None
        db.session.add(interview)
        _set_application_status(application, 'Interview')
    db.session.commit()
    flash('AI interview access granted to selected candidates.', 'success')
    return redirect(url_for('main.recruiter_interviews_job', job_id=job.id))


@main.route('/recruiter/interviews/<int:job_id>/revoke/<int:application_id>', methods=['POST'])
@role_required('recruiter')
def revoke_ai_interview(job_id, application_id):
    application = _recruiter_application_or_404(application_id)
    if application.job_id != job_id:
        abort(404)
    interview = (Interview.query.filter_by(application_id=application.id).filter(Interview.question_set_id.isnot(None)).order_by(Interview.created_at.desc()).first())
    if interview and interview.status == 'Invited':
        interview.status = 'Revoked'
        db.session.commit()
    return redirect(url_for('main.recruiter_interviews_job', job_id=job_id))


@main.route('/interviews')
def interviews():
    if g.user is None:
        return redirect(url_for('main.auth'))
    jobs = Job.query.filter_by(user_id=g.user.id).order_by(Job.title.asc()).all()
    applications = Application.query.join(Job).filter(Job.user_id == g.user.id).all()
    interviewers = User.query.filter_by(company_name=g.user.company_name).order_by(User.first_name.asc()).all()
    return render_template('interviews.html', jobs=jobs, applications=applications, interviewers=interviewers)

def _interview_payload(interview):
    application = interview.application
    candidate = application.user
    job = application.job
    feedback = interview.feedback
    return {
        'id': interview.id,
        'application_id': application.id,
        'candidate': {
            'id': candidate.id,
            'name': f'{candidate.first_name} {candidate.last_name}',
            'email': candidate.email,
            'photo': url_for('static', filename=f'uploads/photos/{candidate.profile_photo}') if candidate.profile_photo else url_for('static', filename='images/default-profile.png'),
            'cv_file': candidate.cv_file,
        },
        'job': {'id': job.id, 'title': job.title},
        'interviewer': {'id': interview.interviewer.id, 'name': f'{interview.interviewer.first_name} {interview.interviewer.last_name}', 'email': interview.interviewer.email},
        'interview_type': interview.interview_type,
        'interview_round': interview.interview_round,
        'scheduled_at': interview.scheduled_at.isoformat(),
        'date': interview.scheduled_at.strftime('%Y-%m-%d'),
        'time': interview.scheduled_at.strftime('%H:%M'),
        'duration_minutes': interview.duration_minutes,
        'meeting_link': interview.meeting_link or '',
        'interviewer_names': interview.interviewer_names or '',
        'scheduled_timezone': interview.scheduled_timezone or 'UTC',
        'notes': interview.notes or '',
        'status': interview.status,
        'decision': interview.decision,
        'feedback': {
            'technical_skills': feedback.technical_skills,
            'communication': feedback.communication,
            'problem_solving': feedback.problem_solving,
            'overall_rating': feedback.overall_rating,
            'comments': feedback.comments,
            'recommendation': feedback.recommendation,
        } if feedback else None,
    }

@main.route('/api/interviews', methods=['GET'])
def api_interviews():
    if g.user is None:
        return jsonify({'error': 'Authentication required.'}), 401
    query = Interview.query.join(Application).join(Job).filter(Job.user_id == g.user.id)
    search = request.args.get('search', '').strip()
    status = request.args.get('status', '').strip()
    job_id = request.args.get('job_id', type=int)
    interviewer_id = request.args.get('interviewer_id', type=int)
    candidate_id = request.args.get('candidate_id', type=int)
    date = request.args.get('date', '').strip()
    if search:
        term = f'%{search}%'
        query = query.join(User, Application.user_id == User.id).filter(db.or_(User.first_name.ilike(term), User.last_name.ilike(term), Job.title.ilike(term)))
    if status in INTERVIEW_STATUSES:
        query = query.filter(Interview.status == status)
    if job_id:
        query = query.filter(Application.job_id == job_id)
    if interviewer_id:
        query = query.filter(Interview.interviewer_id == interviewer_id)
    if candidate_id:
        query = query.filter(Application.user_id == candidate_id)
    if date:
        try:
            day = datetime.strptime(date, '%Y-%m-%d')
            query = query.filter(Interview.scheduled_at >= day, Interview.scheduled_at < day + timedelta(days=1))
        except ValueError:
            return jsonify({'error': 'Invalid date filter.'}), 400
    sort = request.args.get('sort', 'scheduled_at')
    query = query.order_by(Interview.status.asc() if sort == 'status' else Interview.scheduled_at.asc())
    page = max(request.args.get('page', 1, type=int), 1)
    per_page = min(max(request.args.get('per_page', 10, type=int), 1), 50)
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    items = [_interview_payload(item) for item in pagination.items]
    now = datetime.now()
    all_interviews = Interview.query.join(Application).join(Job).filter(Job.user_id == g.user.id).all()
    return jsonify({'items': items, 'pagination': {'page': page, 'pages': pagination.pages, 'total': pagination.total, 'per_page': per_page}, 'summary': {
        'total': len(all_interviews),
        'upcoming': sum(item.scheduled_at >= now and item.status in {'Scheduled', 'Rescheduled'} for item in all_interviews),
        'completed': sum(item.status == 'Completed' for item in all_interviews),
        'pending_feedback': sum(item.status == 'Completed' and item.feedback is None for item in all_interviews),
    }})

@main.route('/api/interviews', methods=['POST'])
def create_interview_api():
    if g.user is None:
        return jsonify({'error': 'Authentication required.'}), 401
    try:
        application_id, interviewer_id, scheduled_at, duration = _parse_interview_payload(request.get_json(silent=True) or {})
    except ValueError as error:
        return jsonify({'error': str(error)}), 400
    application = Application.query.get_or_404(application_id)
    if application.job.user_id != g.user.id:
        return jsonify({'error': 'You can only schedule interviews for your own jobs.'}), 403
    interviewer = User.query.get(interviewer_id)
    if interviewer is None or interviewer.company_name != g.user.company_name:
        return jsonify({'error': 'Interviewer is not available for this organization.'}), 403
    interview = Interview(application=application, interviewer=interviewer, scheduled_at=scheduled_at, duration_minutes=duration, interview_type=request.json['interview_type'], interview_round=request.json['interview_round'], meeting_link=request.json.get('meeting_link', '').strip(), notes=request.json.get('notes', '').strip(), notes_visible=bool(request.json.get('notes_visible', False)))
    db.session.add(interview)
    _set_application_status(application, 'Interview')
    db.session.commit()
    email_sent = _notify_interview(interview, f'Interview scheduled: {application.job.title}', f'Your interview for {application.job.title} is scheduled for {scheduled_at:%B %d, %Y at %H:%M}.')
    return jsonify({'interview': _interview_payload(interview), 'email_sent': email_sent}), 201

@main.route('/api/interviews/<int:interview_id>', methods=['PATCH'])
def update_interview_api(interview_id):
    if g.user is None:
        return jsonify({'error': 'Authentication required.'}), 401
    interview = Interview.query.get_or_404(interview_id)
    if not _interview_owner(interview):
        return jsonify({'error': 'You do not have permission to update this interview.'}), 403
    payload = request.get_json(silent=True) or {}
    if payload.get('status') and payload['status'] not in INTERVIEW_STATUSES:
        return jsonify({'error': 'Invalid interview status.'}), 400
    if payload.get('decision') and payload['decision'] not in INTERVIEW_DECISIONS:
        return jsonify({'error': 'Invalid hiring decision.'}), 400
    if any(key in payload for key in ('date', 'time', 'interviewer_id')):
        merged = {'application_id': interview.application_id, 'interviewer_id': payload.get('interviewer_id', interview.interviewer_id), 'interview_type': payload.get('interview_type', interview.interview_type), 'interview_round': payload.get('interview_round', interview.interview_round), 'date': payload.get('date', interview.scheduled_at.strftime('%Y-%m-%d')), 'time': payload.get('time', interview.scheduled_at.strftime('%H:%M')), 'duration_minutes': payload.get('duration_minutes', interview.duration_minutes)}
        try:
            _, interviewer_id, scheduled_at, duration = _parse_interview_payload(merged, interview)
        except ValueError as error:
            return jsonify({'error': str(error)}), 400
        interviewer = User.query.get(interviewer_id)
        if interviewer is None or interviewer.company_name != g.user.company_name:
            return jsonify({'error': 'Interviewer is not available for this organization.'}), 403
        interview.interviewer_id, interview.scheduled_at, interview.duration_minutes = interviewer_id, scheduled_at, duration
    for key in ('status', 'decision', 'interview_type', 'interview_round', 'meeting_link', 'notes'):
        if key in payload:
            setattr(interview, key, payload[key])
    if 'notes_visible' in payload:
        interview.notes_visible = bool(payload['notes_visible'])
    if interview.status in {'Scheduled', 'Rescheduled'}:
        _set_application_status(interview.application, 'Interview')
    db.session.commit()
    return jsonify({'interview': _interview_payload(interview)})

@main.route('/api/interviews/<int:interview_id>/cancel', methods=['POST'])
def cancel_interview_api(interview_id):
    return update_interview_api(interview_id)

@main.route('/api/interviews/<int:interview_id>/feedback', methods=['POST'])
def interview_feedback_api(interview_id):
    if g.user is None:
        return jsonify({'error': 'Authentication required.'}), 401
    interview = Interview.query.get_or_404(interview_id)
    if not _interview_owner(interview):
        return jsonify({'error': 'You do not have permission to add feedback.'}), 403
    payload = request.get_json(silent=True) or {}
    try:
        ratings = {key: int(payload[key]) for key in ('technical_skills', 'communication', 'problem_solving', 'overall_rating')}
    except (KeyError, TypeError, ValueError):
        return jsonify({'error': 'All rating fields are required.'}), 400
    if any(value < 1 or value > 5 for value in ratings.values()) or not str(payload.get('comments', '')).strip() or payload.get('recommendation') not in INTERVIEW_DECISIONS:
        return jsonify({'error': 'Ratings must be 1-5, comments are required, and recommendation must be valid.'}), 400
    feedback = interview.feedback or InterviewFeedback(interview=interview)
    for key, value in ratings.items():
        setattr(feedback, key, value)
    feedback.comments = payload['comments'].strip()
    feedback.recommendation = payload['recommendation']
    interview.status = 'Completed'
    interview.decision = feedback.recommendation
    if feedback.recommendation == 'Selected':
        _set_application_status(interview.application, 'Offered')
    elif feedback.recommendation == 'Rejected':
        _set_application_status(interview.application, 'Rejected')
    db.session.add(feedback)
    db.session.commit()
    return jsonify({'interview': _interview_payload(interview)})

@main.route('/api/interviews/<int:interview_id>/candidate')
def interview_candidate_api(interview_id):
    if g.user is None:
        return jsonify({'error': 'Authentication required.'}), 401
    interview = Interview.query.get_or_404(interview_id)
    if not _interview_owner(interview):
        return jsonify({'error': 'You do not have permission to view this candidate.'}), 403
    candidate = interview.application.user
    return jsonify({'candidate': _interview_payload(interview)['candidate'], 'application': {'id': interview.application.id, 'status': interview.application.status, 'applied_at': interview.application.timestamp.isoformat(), 'message': interview.application.message}, 'job': {'title': interview.application.job.title, 'description': interview.application.job.description}, 'interviews': [_interview_payload(item) for item in interview.application.interviews]})

@main.route('/resume-screening')
def resume_screening():
    if g.user is None:
        flash('You need to sign in first.', 'danger')
        return redirect(url_for('main.auth'))

    jobs = Job.query.filter_by(user_id=g.user.id).all()
    return render_template('resume_screening.html', jobs=jobs)

@main.route('/resume-screening/analyze', methods=['POST'])
def analyze_resume():
    if g.user is None:
        return jsonify({'error': 'Authentication required.'}), 401

    resume = request.files.get('resume')
    job_description = request.form.get('job_description', '').strip()
    if resume is None or not resume.filename:
        return jsonify({'error': 'Upload a PDF or TXT resume.'}), 400
    if len(job_description) < 80:
        return jsonify({'error': 'Add a detailed job description of at least 80 characters.'}), 400

    filename = secure_filename(resume.filename)
    extension = os.path.splitext(filename)[1].lower()
    if extension not in {'.pdf', '.txt'}:
        return jsonify({'error': 'Only PDF and TXT resumes are supported.'}), 400

    try:
        if extension == '.pdf':
            with pdfplumber.open(resume.stream) as pdf:
                resume_text = '\n'.join(page.extract_text() or '' for page in pdf.pages)
        else:
            resume_text = resume.read().decode('utf-8', errors='ignore')
    except Exception:
        return jsonify({'error': 'The resume could not be read. Try a text-based PDF or TXT file.'}), 422

    if not resume_text.strip():
        return jsonify({'error': 'No readable text was found in this resume.'}), 422

    # Keep protected attributes out of the initial credentials-based analysis.
    protected_patterns = [
        r'(?im)^.*\b(?:date of birth|dob|birthday|age|gender|sex|marital status|nationality)\b.*$',
        r'(?im)^.*\b(?:photo|photograph|headshot)\b.*$',
    ]
    screened_text = resume_text
    for pattern in protected_patterns:
        screened_text = re.sub(pattern, '', screened_text)
    screened_text = re.sub(r'\s+', ' ', screened_text).strip()

    job_terms = set(re.findall(r'[a-zA-Z][a-zA-Z+#.-]{2,}', job_description.lower()))
    resume_terms = set(re.findall(r'[a-zA-Z][a-zA-Z+#.-]{2,}', screened_text.lower()))
    matched_terms = sorted(job_terms & resume_terms)
    word_count = len(screened_text.split())
    saved_name = f"screened_{int(time.time())}_{filename}"
    upload_folder = current_app.config['UPLOAD_FOLDER_CV']
    os.makedirs(upload_folder, exist_ok=True)
    resume.stream.seek(0)
    resume.save(os.path.join(upload_folder, saved_name))

    return jsonify({
        'filename': filename,
        'word_count': word_count,
        'matched_terms': matched_terms[:18],
        'protected_fields_excluded': ['age', 'gender', 'photo', 'nationality', 'marital status'],
        'historical_context_received': bool(request.form.get('historical_context', '').strip()),
        'ats_destination': request.form.get('ats_destination', 'none'),
        'message': 'Resume uploaded and prepared for credentials-based screening.'
    })

@main.route('/get_job_data/<int:job_id>')
def get_job_data(job_id):
    if g.user is None:
        abort(403)

    job = Job.query.get_or_404(job_id)
    if job.user_id != g.user.id:
        abort(403)

    applications = Application.query.filter_by(job_id=job_id).all()
    candidates = []
    ages = []
    questions_responses = []

    for app in applications:
        candidate = User.query.get(app.user_id)
        feedback_data = mongo_safe_find_one({'application_id': str(app.id)})
        if feedback_data is None:
            feedback_data = {'feedback': []}
        total_score = sum(fb['score'] for fb in feedback_data.get('feedback', []) if fb['score'] is not None)

        # Calculate age from birthday
        try:
            birthday = datetime.strptime(candidate.birthday, "%Y-%m-%d")
            today = datetime.now()
            age = today.year - birthday.year - ((today.month, today.day) < (birthday.month, birthday.day))
        except ValueError:
            age = None  # or set a default value if the birthday format is incorrect

        if age is not None:
            ages.append(age)

        candidates.append({
            'name': f"{candidate.first_name} {candidate.last_name}",
            'score': total_score,
            'app_id': app.id  # Store app ID for later use
        })

        # Add questions and responses
        if feedback_data:
            for feedback in feedback_data.get('feedback', []):
                # Handle None score values by setting them to 0
                score = feedback.get('score', 0) or 0
                questions_responses.append({
                    'question': feedback.get('question', ''),
                    'response': feedback.get('response', ''),
                    'score': score
                })

    # Sort candidates by score and select the top 3
    top_candidates = sorted(candidates, key=lambda x: x['score'], reverse=True)[:3]

    # Add similarity score for top 3 candidates
    for candidate in top_candidates:
        app = Application.query.get(candidate['app_id'])
        try:
            similarity_score = float(app.message)
        except ValueError:
            similarity_score = 0.0  # Default value if conversion fails

        candidate['similarity'] = similarity_score  # Add similarity score to top candidates

    # Prepare data for both top candidates and all candidates
    all_candidates = [{'name': c['name'], 'totalScore': c['score'], 'app_id': c['app_id']} for c in candidates]
    scores = [{'name': c['name'], 'totalScore': c['score'], 'similarity': c.get('similarity', 0)} for c in top_candidates]

    return jsonify({
        'topCandidates': top_candidates,
        'allCandidates': all_candidates,
        'scores': scores,
        'ages': ages,
        'questionsResponses': sorted(questions_responses, key=lambda x: x['score'], reverse=True)
    })


@main.route('/recruiter/screening/application/<int:application_id>/shortlist', methods=['POST'])
@role_required('recruiter')
def shortlist_application(application_id):
    application = Application.query.get_or_404(application_id)
    if application.job.user_id != g.user.id:
        abort(403)
    _set_application_status(application, 'Under Review')
    db.session.commit()
    flash('Candidate moved to the shortlist.', 'success')
    return redirect(request.referrer or url_for('main.resume_screening'))


@main.route('/recruiter/screening/<int:job_id>/compare')
@role_required('recruiter')
def compare_resumes(job_id):
    job = Job.query.get_or_404(job_id)
    if job.user_id != g.user.id:
        abort(403)
    raw_ids = request.args.getlist('application_ids')
    if len(raw_ids) == 1 and ',' in raw_ids[0]:
        raw_ids = raw_ids[0].split(',')
    try:
        application_ids = {int(value) for value in raw_ids}
    except (TypeError, ValueError):
        application_ids = set()
    applications = Application.query.filter(Application.job_id == job.id, Application.id.in_(application_ids)).all() if application_ids else []
    if len(applications) < 2:
        flash('Select at least two applicants to compare.', 'warning')
        return redirect(url_for('main.resume_screening'))

    records = []
    for application in applications:
        candidate = application.user
        filename = application.submitted_resume or candidate.cv_file
        resume_text = ''
        if filename:
            resume_path = os.path.join(current_app.config['UPLOAD_FOLDER_CV'], filename)
            if os.path.isfile(resume_path):
                try:
                    resume_text = extract_resume_text(resume_path)
                except (OSError, ValueError):
                    logging.warning('Could not read resume for application %s', application.id)
        feedback_data = mongo_safe_find_one({'application_id': str(application.id)}) or {}
        feedback_scores = [float(item.get('score', 0) or 0) for item in feedback_data.get('feedback', [])]
        score = application.ai_score or (sum(feedback_scores) / len(feedback_scores) / 10 if feedback_scores else 0)
        records.append({
            'application_id': application.id,
            'name': f'{candidate.first_name} {candidate.last_name}',
            'email': candidate.email,
            'applied_at': application.timestamp,
            'resume_filename': filename,
            'score': score,
            'feedback': feedback_data.get('feedback', []),
            'resume_text': resume_text,
            'interviews': application.interviews,
        })
    comparison = rank_resume_comparison(records, job.description)
    return render_template('compare_resumes.html', job=job, comparison=comparison)
