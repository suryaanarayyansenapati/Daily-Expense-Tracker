
from flask import Flask, render_template, request, jsonify
import mysql.connector
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo
import calendar
import os

app = Flask(__name__)

INDIA_TZ = ZoneInfo("Asia/Kolkata")


def get_india_now():
    return datetime.now(INDIA_TZ)


def get_db_connection():
    return mysql.connector.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", "3306")),
        user=os.getenv("DB_USER", "root"),
        password=os.getenv("DB_PASSWORD", ""),
        database=os.getenv("DB_NAME", "expense_tracker"),
        ssl_disabled=False,
        connection_timeout=10
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


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/api/expenses", methods=["GET"])
def get_expenses():
    conn = None
    cursor = None

    try:
        today = get_india_now().date()
        first_day = today - timedelta(days=44)
        tomorrow = today + timedelta(days=1)

        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("""
            SELECT id, expense_date, expense_time, subject, price
            FROM expenses
            WHERE expense_date >= %s
              AND expense_date < %s
            ORDER BY expense_date DESC, expense_time DESC, id DESC
        """, (first_day, tomorrow))

        rows = cursor.fetchall()

        for row in rows:
            row["expense_date"] = row["expense_date"].isoformat()
            row["expense_time"] = str(row["expense_time"])[:5]
            row["price"] = float(row["price"])

        return jsonify(rows)

    except mysql.connector.Error:
        app.logger.exception("Database error while loading expenses")
        return jsonify({
            "error": "Could not load expenses. Check the Render logs."
        }), 500

    finally:
        close_db(conn, cursor)


@app.route("/api/expenses", methods=["POST"])
def add_expense():
    data = request.get_json(silent=True) or {}
    subject = str(data.get("subject", "")).strip()

    try:
        price = float(data.get("price", 0))

        if not subject or len(subject) > 100 or not (0 < price <= 99999999):
            raise ValueError

    except (ValueError, TypeError):
        return jsonify({
            "error": "Enter a subject and a valid amount greater than zero."
        }), 400

    now = get_india_now()
    conn = None
    cursor = None

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO expenses
                (expense_date, expense_time, subject, price)
            VALUES (%s, %s, %s, %s)
        """, (
            now.date(),
            now.time().replace(tzinfo=None, microsecond=0),
            subject,
            price
        ))

        conn.commit()

        return jsonify({
            "message": "Expense added successfully."
        }), 201

    except mysql.connector.Error:
        if conn:
            try:
                conn.rollback()
            except mysql.connector.Error:
                app.logger.exception("Database rollback failed")

        app.logger.exception("Database error while saving expense")
        return jsonify({
            "error": "Could not save the expense. Check the Render logs."
        }), 500

    finally:
        close_db(conn, cursor)


@app.route("/api/monthly-report", methods=["GET"])
def monthly_report():
    today = get_india_now().date()
    first_day_this_month = today.replace(day=1)

    if today.month == 12:
        first_day_next_month = date(today.year + 1, 1, 1)
    else:
        first_day_next_month = date(today.year, today.month + 1, 1)

    days_in_month = calendar.monthrange(today.year, today.month)[1]

    conn = None
    cursor = None

    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("""
            SELECT
                COALESCE(SUM(price), 0) AS total,
                COUNT(*) AS expense_count
            FROM expenses
            WHERE expense_date >= %s
              AND expense_date < %s
        """, (first_day_this_month, first_day_next_month))

        summary = cursor.fetchone()
        total = float(summary["total"])
        count = int(summary["expense_count"])

        cursor.execute("""
            SELECT
                DAY(expense_date) AS day,
                SUM(price) AS total
            FROM expenses
            WHERE expense_date >= %s
              AND expense_date < %s
            GROUP BY expense_date
            ORDER BY expense_date
        """, (first_day_this_month, first_day_next_month))

        daily_rows = cursor.fetchall()

        daily = [
            {
                "day": int(row["day"]),
                "total": float(row["total"])
            }
            for row in daily_rows
        ]

        highest_day = None

        if daily:
            highest = max(daily, key=lambda row: row["total"])
            highest_date = date(
                today.year,
                today.month,
                highest["day"]
            )
            highest_day = highest_date.strftime("%d %b")

        return jsonify({
            "month": today.strftime("%B %Y"),
            "total": total,
            "count": count,
            "daily_average": round(total / days_in_month, 2),
            "highest_day": highest_day,
            "daily": daily
        })

    except mysql.connector.Error:
        app.logger.exception("Database error while generating monthly report")
        return jsonify({
            "error": "Could not generate the monthly report. Check the Render logs."
        }), 500

    finally:
        close_db(conn, cursor)


if __name__ == "__main__":
    app.run(debug=True)
