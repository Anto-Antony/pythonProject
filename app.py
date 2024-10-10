import os

import mysql
from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from db_config import get_db_connection
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import time, timedelta, datetime
import traceback
import requests


app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'secrets.token_hex(16)')

@app.route('/', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']

        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute('SELECT * FROM users WHERE email = %s', (email,))
        user = cursor.fetchone()
        conn.close()

        # flash(f'User from DB: {user}')
        if user:
            if check_password_hash(user['password'], password):
                session['user_id'] = user['id']
                flash('Login successful!', 'success')
                return redirect(url_for('dashboard'))
            else:
                flash('Invalid Password','danger')
        else:
            flash('Invalid credentials, please try again.', 'danger')
    return render_template('login.html', logged_in=False, high_priority_tasks=None)


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

        # Correct the query parameter to be a tuple by adding a comma after (email)
        cursor.execute('SELECT * FROM users WHERE email = %s', (email,))
        user = cursor.fetchone()

        conn.commit()

        # Correct the query parameter to be a tuple by adding a comma after (phone)
        cursor.execute('SELECT * FROM users WHERE phone = %s', (phone,))
        ph_number = cursor.fetchone()

        conn.commit()

        # Insert new user if email and phone do not exist
        if not user and not ph_number:
            cursor.execute('INSERT INTO users (email, phone, profession, password) VALUES (%s, %s, %s, %s)',
                           (email, phone, profession, hashed_password))
        else:
            flash('Account already exists')
            return render_template('register.html', logged_in=False, high_priority_tasks=None)

        conn.commit()
        conn.close()

        flash('Registration successful! You can now log in.', 'success')
        return redirect(url_for('login'))

    return render_template('register.html', logged_in=False, high_priority_tasks=None)


@app.route('/dashboard', methods=['GET'])
def dashboard():
    if 'user_id' not in session:
        flash('Please log in first.', 'danger')
        return redirect(url_for('login'))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        # Fetch all tasks for the logged-in user
        cursor.execute('SELECT task_name, due_date, due_time, priority, description '
                       'FROM tasks WHERE user_id = %s',
                       (session['user_id'],))
        tasks1 = cursor.fetchall()

        for task in tasks1:
            # Format due_date in YYYY-MM-DD format
            task['due_date'] = task['due_date'].strftime('%Y-%m-%d')

            # Handle due_time formatting, check if it's a time or timedelta object
            if isinstance(task['due_time'], time):
                task['due_time'] = task['due_time'].strftime('%H:%M:%S')
            elif isinstance(task['due_time'], timedelta):
                # Convert timedelta to hours and minutes
                total_seconds = int(task['due_time'].total_seconds())
                hours, remainder = divmod(total_seconds, 3600)
                minutes, _ = divmod(remainder, 60)
                task['due_time'] = f"{hours:02}:{minutes:02}:00"  # Assuming seconds are zero

        # Fetch high-priority task dates for the calendar
        cursor.execute('SELECT DISTINCT DATE(due_date) as due_date FROM tasks '
                       'WHERE user_id = %s AND priority = %s',
                       (session['user_id'], 'High'))
        high_priority_tasks = cursor.fetchall()

        tasks = [hp_task['due_date'].strftime('%Y-%m-%d') for hp_task in high_priority_tasks]

        # If no tasks found, set tasks to None
        if not tasks1:
            tasks1 = None

    except Exception as e:
        print(f"Error: {e}")
        traceback.print_exc()
        flash('An error occurred while fetching tasks.', 'danger')
        return jsonify({'error': 'An error occurred while fetching tasks'}), 500
    finally:
        conn.close()

    # Render the dashboard with all tasks
    return render_template('dashboard.html', logged_in=True, tasks=tasks1, high_priority_tasks=tasks)




@app.route('/create_task', methods=['GET', 'POST'])
def create_task():
    if 'user_id' not in session:
        flash('Please log in first.', 'danger')
        return redirect(url_for('login'))

    if request.method == 'POST':
        task_description_input = request.form['task_description_input']  # Get task description input
        # Call Gemini API to generate task details
        api_url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash-latest:generateContent?key=AIzaSyBTsIFup_qC0CmUzJw8KWjL_Shyjr6gMfY"
        headers = {'Authorization': 'Bearer AIzaSyBTsIFup_qC0CmUzJw8KWjL_Shyjr6gMfY', 'Content-Type': 'application/json'}
        payload = {"input": task_description_input}
        response = requests.post(api_url, json=payload, headers=headers)

        if response.status_code == 200:
            tasks = response.json().get('taskDetails', [])  # Assuming task details returned
            conn = get_db_connection()
            cursor = conn.cursor()

            try:
                for task in tasks:
                    cursor.execute(
                        'INSERT INTO tasks (user_id, task_name, due_date, due_time, priority, description, recurring, recurring_type) '
                        'VALUES (%s, %s, %s, %s, %s, %s, %s, %s)',
                        (session['user_id'], task['taskName'], task['dueDate'], task['dueTime'], task['priority'],
                         task['description'], task['recurring'], task['recurringType'])
                    )
                conn.commit()
                flash('Tasks created successfully!', 'success')
                # Fetch high-priority task dates for the calendar
                cursor.execute('SELECT DISTINCT DATE(due_date) as due_date FROM tasks '
                               'WHERE user_id = %s AND priority = %s',
                               (session['user_id'], 'High'))
                high_priority_tasks = cursor.fetchall()

                tasks = [hp_task['due_date'].strftime('%Y-%m-%d') for hp_task in high_priority_tasks]

            except mysql.connector.Error as err:
                flash(f'Error: {err}', 'danger')
            finally:
                cursor.close()
                conn.close()
        else:
            flash('Error with Gemini API', 'danger')

    # Fetch high-priority task dates
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute('SELECT DISTINCT DATE(due_date) as due_date FROM tasks '
                   'WHERE user_id = %s AND priority = %s',
                   (session['user_id'], 'High'))
    high_priority_tasks = cursor.fetchall()

    # Format high-priority dates for passing to the template
    high_priority_dates = [task['due_date'].strftime('%Y-%m-%d') for task in high_priority_tasks]

    cursor.close()
    conn.close()

    return render_template('create_task.html', logged_in=True, high_priority_tasks=high_priority_dates)

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
        cursor.execute('SELECT due_date FROM tasks WHERE user_id = %s AND priority = %s', (session['user_id'], 'High'))
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
    return render_template('manage_tasks.html', logged_in=True, task=task, high_priority_tasks=task_dates, todays_tasks=todays_tasks)


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
        recurring = request.form.get('recurring')  # Checkbox for recurring task
        recurring_type = int(request.form['recurring_type'])
        is_recurring = 1 if recurring else 0

        try:
            cursor.execute(
                'UPDATE tasks SET task_name = %s, due_date = %s, due_time = %s, priority = %s, description = %s, recurring = %s, recurring_type = %s WHERE '
                'id = %s AND user_id = %s',
                (task_name, due_date, due_time, priority, description,  is_recurring, recurring_type, task_id, session['user_id']))
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
    return render_template('edit_task.html', logged_in=logged_in, task=task, high_priority_tasks=task_dates,
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


@app.route('/logout')
def logout():
    session.pop('user_id', None)
    flash('Logged out successfully.', 'success')
    return redirect(url_for('login'))


if __name__ == '__main__':
    app.run(debug=True)
