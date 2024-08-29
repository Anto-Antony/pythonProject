import os

import mysql
from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from db_config import get_db_connection
from werkzeug.security import generate_password_hash, check_password_hash

from datetime import datetime, timedelta

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'secrets.token_hex(16)')


@app.route('/', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']

        conn = get_db_connection()               
        cursor = conn.cursor(dictionary=True)
        cursor.execute('SELECT * FROM users WHERE email = %s AND password = %s', (email, password))
        user = cursor.fetchone()
        conn.close()

        flash(f'User from DB: {user}')
        if user and check_password_hash(user['password'], password):
            session['user_id'] = user['id']
            flash('Login successful!', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid credentials, please try again.', 'danger')
    return render_template('login.html', logged_in=False, tasks=None, todays_tasks=None)


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        email = request.form['email']
        phone = request.form['phone']
        profession = request.form['profession']
        password = request.form['password']
        confirm_password = request.form['confirm_password']

        if password != confirm_password:
            flash('Passwords do not match.', 'danger')
            return redirect(url_for('register'))

        hashed_password = generate_password_hash(password, method='pbkdf2:sha256', salt_length=16)

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('INSERT INTO users (email, phone, profession, password) VALUES (%s, %s, %s, %s)',
                       (email, phone, profession, hashed_password))
        conn.commit()
        conn.close()

        flash('Registration successful! You can now log in.', 'success')
        return redirect(url_for('login'))

    return render_template('register.html', logged_in=False, tasks=None, todays_tasks=None)


@app.route('/dashboard', methods=['GET'])
def dashboard():
    if 'user_id' not in session:
        flash('Please log in first.', 'danger')
        return redirect(url_for('login'))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    date_str = request.args.get('date')
    direction = request.args.get('direction', 'today')

    try:
        if date_str:
            date = datetime.strptime(date_str, '%Y-%m-%d').date()
        else:
            date = datetime.today().date()

        task = []
        high_priority_tasks = []

        while not task:
            cursor.execute('SELECT task_name, due_time, priority, description '
                           'FROM tasks WHERE user_id = %s AND DATE(due_date) = %s',
                           (session['user_id'], date))
            task = cursor.fetchall()

            cursor.execute('SELECT due_date FROM tasks WHERE user_id = %s AND priority = %s',
                           (session['user_id'], 'High'))
            high_priority_tasks = cursor.fetchall()

            if task:
                break

            if direction == 'down':
                date += timedelta(days=1)
            elif direction == 'up':
                date -= timedelta(days=1)
            else:
                break

            if date > datetime.today().date() + timedelta(days=365) or date < datetime.today().date() - timedelta(
                    days=365):
                break

    except Exception as e:
        print(f"Database error: {e}")
        flash('An error occurred while fetching tasks.', 'danger')
        return jsonify({'error': 'An error occurred while fetching tasks'}), 500
    finally:
        conn.close()

    tasks = [task['due_date'].strftime('%Y-%m-%d') for task in high_priority_tasks]

    return render_template('dashboard.html', logged_in=True, task=task, tasks=tasks, current_date=date)


@app.route('/create_task', methods=['GET', 'POST'])
def create_task():
    # Check if the user is logged in
    if 'user_id' not in session:
        flash('Please log in first.', 'danger')
        return redirect(url_for('login'))

    if request.method == 'POST':
        # Get form data
        task_name = request.form['task_name']
        due_date = request.form['due_date']
        due_time = request.form['due_time']
        priority = request.form['priority']
        description = request.form['description']

        # Database connection and task insertion
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                'INSERT INTO tasks (user_id, task_name, due_date, due_time, priority, description) VALUES (%s, %s, '
                '%s, %s, %s, %s)',
                (session['user_id'], task_name, due_date, due_time, priority, description)
            )
            conn.commit()
            flash('Task created successfully!', 'success')
        except mysql.connector.Error as err:
            flash(f'Error: {err}', 'danger')
        finally:
            cursor.close()
            conn.close()

    # Fetch high priority task dates and today's tasks
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute('SELECT due_date FROM tasks WHERE user_id = %s AND priority = %s', (session['user_id'], 'High'))
    high_priority_tasks = cursor.fetchall()

    cursor.close()
    conn.close()

    # Extract dates for high priority tasks
    task_dates = [task['due_date'].strftime('%Y-%m-%d') for task in high_priority_tasks]

    # Render the create_task template and pass the variables
    return render_template('create_task.html', logged_in=True, tasks=task_dates)


@app.route('/manage_tasks')
def manage_tasks():
    # Check if the user is logged in
    if 'user_id' not in session:
        flash('Please log in first.', 'danger')
        return redirect(url_for('login'))

    # Database connection
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        # Fetch all tasks for the logged-in user
        cursor.execute('SELECT * FROM tasks WHERE user_id = %s', (session['user_id'],))
        task = cursor.fetchall()

        # Fetch high priority task dates
        cursor.execute('SELECT due_date FROM tasks WH   ERE user_id = %s AND priority = %s', (session['user_id'], 'High'))
        high_priority_tasks = cursor.fetchall()

        # Fetch today's tasks
        cursor.execute('SELECT * FROM tasks WHERE user_id = %s AND due_date = %s',
                       (session['user_id'], datetime.today().date()))
        todays_tasks = cursor.fetchall()
    finally:
        cursor.close()
        conn.close()

    # Extract dates for high priority tasks
    task_dates = [task['due_date'].strftime('%Y-%m-%d') for task in high_priority_tasks]

    # Return the necessary variables
    return render_template('manage_tasks.html', logged_in=True, task=task, tasks=task_dates, todays_tasks=todays_tasks)


@app.route('/edit_task/<int:task_id>', methods=['GET', 'POST'])
def edit_task(task_id):
    if 'user_id' not in session:
        flash('Please log in first.', 'danger')
        return redirect(url_for('login'))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    if request.method == 'POST':
        task_name = request.form['task_name']
        due_date = request.form['due_date']
        due_time = request.form['due_time']
        priority = request.form['priority']
        description = request.form['description']

        try:
            cursor.execute(
                'UPDATE tasks SET task_name = %s, due_date = %s, due_time = %s, priority = %s, description = %s WHERE '
                'id = %s AND user_id = %s',
                (task_name, due_date, due_time, priority, description, task_id, session['user_id']))
            conn.commit()
        finally:
            conn.close()

        return redirect(url_for('manage_tasks'))

    try:
        cursor.execute('SELECT * FROM tasks WHERE id = %s AND user_id = %s', (task_id, session['user_id']))
        task = cursor.fetchone()

        # Fetch high priority task dates
        cursor.execute('SELECT due_date FROM tasks WHERE user_id = %s AND priority = %s', (session['user_id'], 'High'))
        high_priority_tasks = cursor.fetchall()

        # Fetch today's tasks
        cursor.execute('SELECT * FROM tasks WHERE user_id = %s AND due_date = %s',
                       (session['user_id'], datetime.today().date()))
        todays_tasks = cursor.fetchall()

        # Extract dates for high priority tasks
        task_dates = [task['due_date'].strftime('%Y-%m-%d') for task in high_priority_tasks]
    finally:
        cursor.close()
        conn.close()

    if not task:
        return redirect(url_for('manage_tasks'))

    logged_in = 'user_id' in session
    return render_template('edit_task.html', logged_in=logged_in, task=task, tasks=task_dates,
                           todays_tasks=todays_tasks)


@app.route('/delete_task/<int:task_id>')
def delete_task(task_id):
    if 'user_id' not in session:
        flash('Please log in first.', 'danger')
        return redirect(url_for('login'))

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('DELETE FROM tasks WHERE id = %s AND user_id = %s', (task_id, session['user_id']))
        conn.commit()
    finally:
        conn.close()

    return redirect(url_for('manage_tasks'))


@app.route('/header')
def addheader():
    if 'user_id' not in session:
        flash('Please log in first.', 'danger')
        return render_template('header.html', logged_in=False)

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        # Fetch high-priority tasks for the calendar
        cursor.execute('SELECT due_date FROM tasks WHERE user_id = %s AND priority = %s',
                       (session['user_id'], 'High'))
        tasks = cursor.fetchall()

        # Fetch today's tasks with priority
        today = datetime.today().date()
        cursor.execute('SELECT task_name, due_date, priority FROM tasks WHERE user_id = %s AND due_date = %s',
                       (session['user_id'], today))
        todays_tasks = cursor.fetchall()
    finally:
        conn.close()

    # Extract the dates of high-priority tasks
    task_dates = [task['due_date'].strftime('%Y-%m-%d') for task in tasks]
    return render_template('header.html', tasks=task_dates, todays_tasks=todays_tasks, logged_in=True)


@app.route('/logout')
def logout():
    session.pop('user_id', None)
    flash('Logged out successfully.', 'success')
    return redirect(url_for('login'))


if __name__ == '__main__':
    app.run(debug=True)
