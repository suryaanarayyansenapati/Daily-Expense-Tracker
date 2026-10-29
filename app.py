
import os
import hmac
import secrets
import calendar
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo

import mysql.connector
from flask import (
    Flask, render_template, request, jsonify,
    session, redirect, url_for
)
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("RENDER") == "true",
    PERMANENT_SESSION_LIFETIME=timedelta(days=7),
)

INDIA_TZ = ZoneInfo("Asia/Kolkata")


def get_india_now():
    return datetime.now(INDIA_TZ)


def get_db_connection():
    return mysql.connector.connect(
        host=os.environ["DB_HOST"],
        port=int(os.environ.get("DB_PORT", "3306")),
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        database=os.environ["DB_NAME"],
        ssl_disabled=False,
        connection_timeout=10,
    )


def close_db(conn=None, cursor=None):
    if cursor:
        try:
            cursor.close()
        except Exception:
            app.logger.exception("Error closing database cursor")
    if conn:
        try:
            conn.close()
        except Exception:
            app.logger.exception("Error closing database connection")


def logged_in_user():
    return session.get("user_id")


def login_required():
    if not logged_in_user():
        return jsonify({"error": "Please log in first."}), 401
    return None


@app.route("/")
def home():
    if not logged_in_user():
        return redirect(url_for("login_page"))
    return render_template("index.html")


@app.route("/login")
def login_page():
    if logged_in_user():
        return redirect(url_for("home"))
    return render_template("login.html")


@app.route("/api/register", methods=["POST"])
def register():
    data = request.get_json(silent=True) or {}
    username = str(data.get("username", "")).strip()
    email = str(data.get("email", "")).strip().lower()
    password = data.get("password", "")

    if (
        not username or len(username) < 3 or len(username) > 40
        or not username.replace("_", "").replace("-", "").isalnum()
        or len(email) > 254 or "@" not in email
        or not isinstance(password, str) or len(password) < 10
        or len(password) > 128
    ):
        return jsonify({
            "error": "Use a username of 3–40 letters, numbers, _ or -. Enter a valid email and a password of 10–128 characters."
        }), 400

    conn = cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id FROM users WHERE username = %s OR email = %s",
            (username, email),
        )
        if cursor.fetchone():
            return jsonify({
                "error": "That username or email is already registered."
            }), 409

        password_hash = generate_password_hash(password)
        cursor.execute(
            """
            INSERT INTO users (username, email, password_hash)
            VALUES (%s, %s, %s)
            """,
            (username, email, password_hash),
        )
        user_id = cursor.lastrowid
        conn.commit()

        session.clear()
        session["user_id"] = user_id
        session["username"] = username
        session.permanent = True
        return jsonify({"message": "Account created successfully."}), 201

    except mysql.connector.Error:
        if conn:
            conn.rollback()
        app.logger.exception("Registration database error")
        return jsonify({"error": "Could not create the account. Please try again."}), 500
    finally:
        close_db(conn, cursor)


@app.route("/api/login", methods=["POST"])
def login():
    data = request.get_json(silent=True) or {}
    identity = str(data.get("identity", "")).strip()
    password = data.get("password", "")

    if not identity or not isinstance(password, str) or not password:
        return jsonify({"error": "Enter your username/email and password."}), 400

    conn = cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT id, username, password_hash
            FROM users
            WHERE username = %s OR email = %s
            LIMIT 1
            """,
            (identity, identity.lower()),
        )
        user = cursor.fetchone()

        if not user or not check_password_hash(user["password_hash"], password):
            return jsonify({"error": "Incorrect username/email or password."}), 401

        session.clear()
        session["user_id"] = user["id"]
        session["username"] = user["username"]
        session.permanent = True
        return jsonify({"message": "Logged in successfully."})

    except mysql.connector.Error:
        app.logger.exception("Login database error")
        return jsonify({"error": "Could not log in. Please try again."}), 500
    finally:
        close_db(conn, cursor)


@app.route("/api/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"message": "Logged out successfully."})


@app.route("/api/me", methods=["GET"])
def me():
    if not logged_in_user():
        return jsonify({"logged_in": False}), 401
    return jsonify({
        "logged_in": True,
        "username": session.get("username", ""),
    })


@app.route("/api/expenses", methods=["GET"])
def get_expenses():
    auth_error = login_required()
    if auth_error:
        return auth_error

    today = get_india_now().date()
    first_day = today - timedelta(days=44)
    tomorrow = today + timedelta(days=1)
    conn = cursor = None

    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT id, expense_date, expense_time, subject, price
            FROM expenses
            WHERE user_id = %s
              AND expense_date >= %s
              AND expense_date < %s
            ORDER BY expense_date DESC, expense_time DESC, id DESC
            """,
            (logged_in_user(), first_day, tomorrow),
        )
        rows = cursor.fetchall()
        for row in rows:
            row["expense_date"] = row["expense_date"].isoformat()
            row["expense_time"] = str(row["expense_time"])[:5]
            row["price"] = float(row["price"])
        return jsonify(rows)

    except mysql.connector.Error:
        app.logger.exception("Error loading expenses")
        return jsonify({"error": "Could not load expenses."}), 500
    finally:
        close_db(conn, cursor)


@app.route("/api/expenses", methods=["POST"])
def add_expense():
    auth_error = login_required()
    if auth_error:
        return auth_error

    data = request.get_json(silent=True) or {}
    subject = str(data.get("subject", "")).strip()

    try:
        price = float(data.get("price", 0))
        if not subject or len(subject) > 100 or not (0 < price <= 99999999):
            raise ValueError
    except (ValueError, TypeError):
        return jsonify({"error": "Enter a subject and a valid amount greater than zero."}), 400

    now = get_india_now()
    conn = cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO expenses
                (user_id, expense_date, expense_time, subject, price)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (
                logged_in_user(),
                now.date(),
                now.time().replace(tzinfo=None, microsecond=0),
                subject,
                price,
            ),
        )
        conn.commit()
        return jsonify({"message": "Expense added successfully."}), 201

    except mysql.connector.Error:
        if conn:
            conn.rollback()
        app.logger.exception("Error saving expense")
        return jsonify({"error": "Could not save the expense."}), 500
    finally:
        close_db(conn, cursor)


@app.route("/api/monthly-report", methods=["GET"])
def monthly_report():
    auth_error = login_required()
    if auth_error:
        return auth_error

    today = get_india_now().date()
    first_day = today.replace(day=1)
    if today.month == 12:
        next_month = date(today.year + 1, 1, 1)
    else:
        next_month = date(today.year, today.month + 1, 1)

    days_in_month = calendar.monthrange(today.year, today.month)[1]
    conn = cursor = None

    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT COALESCE(SUM(price), 0) AS total, COUNT(*) AS expense_count
            FROM expenses
            WHERE user_id = %s
              AND expense_date >= %s AND expense_date < %s
            """,
            (logged_in_user(), first_day, next_month),
        )
        summary = cursor.fetchone()
        total = float(summary["total"])
        count = int(summary["expense_count"])

        cursor.execute(
            """
            SELECT DAY(expense_date) AS day, SUM(price) AS total
            FROM expenses
            WHERE user_id = %s
              AND expense_date >= %s AND expense_date < %s
            GROUP BY expense_date
            ORDER BY expense_date
            """,
            (logged_in_user(), first_day, next_month),
        )
        daily = [
            {"day": int(row["day"]), "total": float(row["total"])}
            for row in cursor.fetchall()
        ]

        highest_day = None
        if daily:
            highest = max(daily, key=lambda row: row["total"])
            highest_day = date(today.year, today.month, highest["day"]).strftime("%d %b")

        return jsonify({
            "month": today.strftime("%B %Y"),
            "total": total,
            "count": count,
            "daily_average": round(total / days_in_month, 2),
            "highest_day": highest_day,
            "daily": daily,
        })

    except mysql.connector.Error:
        app.logger.exception("Error generating monthly report")
        return jsonify({"error": "Could not generate the monthly report."}), 500
    finally:
        close_db(conn, cursor)


if __name__ == "__main__":
    app.run(debug=False)
