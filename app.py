import os
from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from db_config import get_db_connection
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import date, time, timedelta, datetime
import traceback
import google.generativeai as genai
import json
import re

from flask_wtf import CSRFProtect


# Configure the Google Gemini API
genai.configure(api_key="AIzaSyAuM-2PrKXO-sXOQUYr6Ff4lZ5HmzPNk_c")
model = genai.GenerativeModel('gemini-1.5-flash')
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
                flash('Invalid Password', 'danger')
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


# Route for the create task page
@app.route('/create_task', methods=['GET', 'POST'])
def create_task():
    if 'user_id' not in session:
        flash('Please log in first.', 'danger')
        return redirect(url_for('login'))

    tasks = []  # Initialize tasks as an empty list

    if request.method == 'POST':
        # Get the tasks from the form
        task_names = request.form.getlist('task_name[]')
        descriptions = request.form.getlist('description[]')
        due_dates = request.form.getlist('due_date[]')
        due_times = request.form.getlist('due_time[]')

        # Save each task in the database
        conn = get_db_connection()
        cursor = conn.cursor()

        try:
            for task_name, description, due_date, due_time in zip(task_names, descriptions, due_dates, due_times):
                cursor.execute(
                    '''
                    INSERT INTO tasks (user_id, task_name, due_date, due_time, priority, description, recurring, recurring_type)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ''',
                    (session['user_id'], task_name, due_date or None, due_time or None, 'Low', description, 0, 0)
                )
            conn.commit()
            flash('Tasks created successfully!', 'success')
        except Exception as e:
            flash(f'Error saving tasks: {str(e)}', 'danger')
            conn.rollback()
        finally:
            cursor.close()

        # Fetch high-priority task dates for the calendar
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            '''
            SELECT DISTINCT DATE(due_date) as due_date FROM tasks
            WHERE user_id = %s AND priority = %s
            ''',
            (session['user_id'], 'High')
        )
        high_priority_tasks = cursor.fetchall()
        tasks = [hp_task['due_date'].strftime('%Y-%m-%d') for hp_task in high_priority_tasks]

        cursor.close()
        conn.close()

    # If no high-priority tasks are found, ensure `tasks` remains an empty list
    if not tasks:
        tasks = []

    return render_template('create_task.html', logged_in=True, high_priority_tasks=tasks)


# Route to handle task extraction using the Gemini API
@app.route('/extract_task_details', methods=['POST'])
def extract_task_details():
    data = request.json
    passage = data.get('text', '')

    # Get today's date in DD/MM/YY format
    today_date = datetime.now().strftime("%d/%m/%Y")

    # Create the prompt for the Gemini model
    prompt = f"""
        Extract all tasks mentioned in the following paragraph and format them as a valid JSON array. Each task should have a short and meaningful heading, a detailed description, a date (in DD/MM/YY format, using today's date {today_date} if not provided), and a time (in HH:MM:00 format, using '00:00:00' if time is not provided). Each task should be a separate JSON object in the array.

        Example output:
        [
            {{
                "Heading": "Client Meeting",
                "Description": "Schedule a meeting with the client for the project discussion.",
                "Date": "23/10/2024",
                "Time": "10:00:00"
            }},
            {{
                "Heading": "Submit Report",
                "Description": "Submit the final project report to the manager by the end of the day.",
                "Date": "23/10/2024",
                "Time": "17:00:00"
            }}
        ]

        Paragraph: "{passage}"
    """

    try:
        # Generate content using the Google Gemini API
        response = model.generate_content(prompt)

        # Access the generated content (Assuming 'text' or similar is the correct attribute)
        response_text = response.text if hasattr(response, 'text') else str(response)

        cleaned_response_text = re.sub(r'```json|```', '', response_text).strip()

        # Validate JSON format before sending it back
        try:
            parsed_json = json.loads(cleaned_response_text)
            print(parsed_json)
        except json.JSONDecodeError as e:
            print(f"Error decoding JSON: {e}")
            print(f"Cleaned response: {cleaned_response_text}")
            # Return an error message as JSON for debugging purposes
            return jsonify({"error": "Invalid JSON format generated by AI", "details": cleaned_response_text}), 500

        # If JSON is valid, proceed to return it
        return jsonify({'result': parsed_json})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# Route to manage tasks and categories
@app.route('/manage_tasks')
def manage_tasks():
    if 'user_id' not in session:
        flash('Please log in first.', 'danger')
        return redirect(url_for('login'))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        # Fetch all tasks and their categories for the logged-in user
        cursor.execute('''
            SELECT tasks.*, categories.name AS category_name, categories.id AS category_id
            FROM tasks
            LEFT JOIN categories ON tasks.category_id = categories.id
            WHERE tasks.user_id = %s
        ''', (session['user_id'],))
        tasks = cursor.fetchall()

        # Fetch all available categories
        cursor.execute('SELECT * FROM categories WHERE user_id = %s', (session['user_id'],))
        categories = cursor.fetchall()
        # Fetch high-priority task dates for the calendar
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            '''
            SELECT DISTINCT DATE(due_date) as due_date FROM tasks
            WHERE user_id = %s AND priority = %s
            ''',
            (session['user_id'], 'High')
        )
        high_priority_tasks = cursor.fetchall()
        high_tasks = [hp_task['due_date'].strftime('%Y-%m-%d') for hp_task in high_priority_tasks]

    finally:
        cursor.close()
        conn.close()

        # If no high-priority tasks are found, ensure `tasks` remains an empty list
    if not tasks:
        tasks = []

    return render_template('manage_tasks.html', logged_in=True, tasks=tasks, high_priority_tasks=high_tasks,
                           categories=categories)


# Route to create a new category
@app.route('/create_category', methods=['POST'])
def create_category():
    if 'user_id' not in session:
        flash('Please log in first.', 'danger')
        return redirect(url_for('login'))

    category_name = request.form.get('category_name')
    if not category_name:
        flash('Category name is required.', 'danger')
        return redirect(url_for('manage_tasks'))

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('INSERT INTO categories (name, user_id) VALUES (%s, %s)', (category_name, session['user_id']))
        conn.commit()
        flash('Category created successfully!', 'success')
    except Exception as e:
        flash(f'Error creating category: {str(e)}', 'danger')
    finally:
        cursor.close()
        conn.close()

    return redirect(url_for('manage_tasks'))


# Route to update a task's category
@app.route('/update_task_category/<int:task_id>', methods=['POST'])
def update_task_category(task_id):
    if 'user_id' not in session:
        flash('Please log in first.', 'danger')
        return redirect(url_for('login'))

    category_id = request.form.get('category_id')

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('''
            UPDATE tasks
            SET category_id = %s
            WHERE id = %s AND user_id = %s
        ''', (category_id if category_id else None, task_id, session['user_id']))
        conn.commit()
        flash('Task category updated successfully!', 'success')
    except Exception as e:
        flash(f'Error updating task category: {str(e)}', 'danger')
    finally:
        cursor.close()
        conn.close()

    return redirect(url_for('manage_tasks'))


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
                'UPDATE tasks SET task_name = %s, due_date = %s, due_time = %s, priority = %s, description = %s, '
                'recurring = %s, recurring_type = %s WHERE'
                'id = %s AND user_id = %s',
                (task_name, due_date, due_time, priority, description, is_recurring, recurring_type, task_id,
                 session['user_id']))
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

@app.route('/generate_categories', methods=['POST'])
def generate_categories():
    # Check if the user is logged in
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Please log in first.'})

    # Database connection
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        # Fetch tasks with NULL categories for the logged-in user
        cursor.execute('SELECT * FROM tasks WHERE user_id = %s AND category_id IS NULL', (session['user_id'],))
        tasks = cursor.fetchall()

        # If no tasks need categorization, return early
        if not tasks:
            return jsonify({'success': False, 'message': 'No tasks with NULL categories to categorize.'})

        # Convert tasks to JSON-friendly format by serializing dates to strings
        for task in tasks:
            if isinstance(task.get('due_date'), (date, datetime)):
                task['due_date'] = task['due_date'].strftime('%Y-%m-%d')
            if isinstance(task.get('due_time'), (date, datetime)):
                task['due_time'] = task['due_time'].strftime('%H:%M:%S')

        # Convert tasks to JSON format
        try:
            tasks_json = json.dumps(tasks, indent=2)
        except (TypeError, ValueError) as e:
            print(f"Error converting tasks to JSON: {e}")
            return jsonify({'success': False, 'message': 'Error processing task data.'})

        # Prepare the prompt for AI
        prompt = f"""
        You are provided with a list of tasks stored in a MySQL table named `tasks` with a reference to a `categories` table. Each task may or may not have a category assigned to it. Your job is to generate SQL `UPDATE` queries that assign appropriate `category_id` values to tasks based on their descriptions. Use the following structure:

        **Table `tasks`:**
        - `id` (INT): The unique identifier for the task.
        - `task_name` (VARCHAR): The name of the task.
        - `description` (TEXT): A description of the task.
        - `due_date` (DATE): The due date for the task.
        - `category_id` (INT): The category of the task, which may be NULL if not assigned.

        **Table `categories`:**
        - `id` (INT): The unique identifier for the category.
        - `name` (VARCHAR): The name of the category.
        - `user_id` (BIGINT(20)): Corresponds to the user who owns the category. In this case, user_id is {session['user_id']}.

        **Task Data:**
        {tasks_json}

        **Examples for categorization:** 
        1. If a task's description contains "meeting" or "client", categorize it as "Client Management".
        2. If a task's description contains "proposal" or "complete", categorize it as "Project Work".
        3. If a task's description contains "contract" or "follow up", categorize it as "Administration".

        **Example of inserting a new category into the `categories` table if it doesn't exist:**
        INSERT INTO categories (name, user_id) VALUES ('Client Management', {session['user_id']});

        **Generate the MySQL `UPDATE` queries for tasks with NULL `category_id` values according to these rules. Ensure the `category_id` is updated in the `tasks` table using the appropriate `id` from the `categories` table for each category name.**
        """

        # Generate the response from the AI
        try:
            # Generate content using the AI model
            response = model.generate_content(prompt)
            # Extract the generated SQL query from the AI response
            generated_query = response.text.strip()

            print("Generated SQL Query:")
            print(generated_query)

            # Execute the generated SQL query
            cursor.execute(generated_query)
            conn.commit()

            return jsonify({'success': True, 'message': 'Categories generated and updated successfully.'})

        except Exception as e:
            print(f"An error occurred: {str(e)}")
            return jsonify({'success': False, 'message': 'Error generating or executing AI-based queries.'})

    finally:
        cursor.close()
        conn.close()


@app.route('/logout')
def logout():
    session.pop('user_id', None)
    flash('Logged out successfully.', 'success')
    return redirect(url_for('login'))


if __name__ == '__main__':
    app.run(debug=True)
