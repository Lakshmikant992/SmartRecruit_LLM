from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from werkzeug.security import check_password_hash, generate_password_hash
from .models import User, db

auth_bp = Blueprint('auth', __name__, url_prefix='/auth')

@auth_bp.route('/sign', methods=['GET', 'POST'])
def sign():
    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'signup':
            first_name = request.form['first_name']
            last_name = request.form['last_name']
            role = request.form.get('role', 'recruiter').strip().lower() or 'recruiter'
            company_name = request.form['company_name']
            email = request.form['email']
            phone_number = request.form['phone_number']
            birthday = request.form['birthday']
            password = request.form['password']
            confirm_password = request.form['confirm_password']

            if password != confirm_password:
                flash('Passwords do not match.', 'danger')
                return redirect(url_for('auth.sign'))

            user = User(first_name=first_name, last_name=last_name, company_name=company_name,
                        email=email, phone_number=phone_number, birthday=birthday,
                        password=generate_password_hash(password), role=role)
            db.session.add(user)
            db.session.commit()
            flash('Signup successful! You can now sign in.', 'success')
            return redirect(url_for('auth.sign'))

        elif action == 'signin':
            email = request.form['email']
            password = request.form['password']
            user = User.query.filter_by(email=email).first()
            password_matches = user and (check_password_hash(user.password, password) if user.password.startswith(('scrypt:', 'pbkdf2:')) else user.password == password)
            if user and password_matches:
                if not user.password.startswith(('scrypt:', 'pbkdf2:')):
                    user.password = generate_password_hash(password)
                    db.session.commit()
                session['user_id'] = user.id
                flash('Signin successful!', 'success')
                return redirect(url_for('job_listings'))
            else:
                flash('Invalid email or password.', 'danger')

    return render_template('sign.html')

@auth_bp.route('/logout')
def logout():
    session.pop('user_id', None)
    session.clear()
    flash('You have been logged out.', 'success')
    return redirect(url_for('auth.sign'))
