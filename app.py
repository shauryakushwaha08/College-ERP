import calendar
import csv
import io
import json
import os
from datetime import datetime, timedelta

import matplotlib

matplotlib.use("Agg")  # draw charts into memory (no window needed)
import matplotlib.pyplot as plt
from flask import Flask, Response, flash, jsonify, redirect, render_template, request, url_for

app = Flask(__name__)
app.secret_key = "college-erp-mini-project"  # needed for flash messages
DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data.json")
DATE_FORMAT = "%d-%m-%Y"  # every date in the app is DD-MM-YYYY


# Custom exceptions
class ERPError(Exception):
    status = 400


class ValidationError(ERPError):
    status = 400


class NotFoundError(ERPError):
    status = 404


class ConflictError(ERPError):
    status = 409


class StorageError(ERPError):
    status = 500



# Date helpers:
def today_str():
    return datetime.now().strftime(DATE_FORMAT)


def parse_date(text):
    text = str(text).strip()
    try:
        return datetime.strptime(text, DATE_FORMAT).strftime(DATE_FORMAT)
    except ValueError:
        pass

    try:
        day, month, year = (int(p) for p in text.split("-"))
        last = calendar.monthrange(year, month)[1]
        if day > last:
            raise ValidationError(f"{calendar.month_name[month]} {year} has only {last} days.")
    except ValueError:
        pass
    raise ValidationError("Dates must be in DD-MM-YYYY format, for example 25-12-2026.")


def clamp_to_month(text):
    try:
        day, month, year = (int(p) for p in text.split("-"))
        last = calendar.monthrange(year, month)[1]
    except ValueError:
        return text
    if day > last:
        flash(f"{calendar.month_name[month]} {year} has only {last} days, so {last:02d}-{month:02d}-{year} is shown.", "ok")
        return f"{last:02d}-{month:02d}-{year}"
    return text


def shift_day(day, days):
    return (datetime.strptime(day, DATE_FORMAT) + timedelta(days=days)).strftime(DATE_FORMAT)


def day_name(day):
    return datetime.strptime(day, DATE_FORMAT).strftime("%A")


def year_choices(day):
    this_year = datetime.now().year
    years = set(range(this_year - 5, this_year + 2))
    years.add(int(day.split("-")[2]))
    return [str(y) for y in sorted(years)]

# Storage helpers:
def empty_data():
    return {"students": [], "attendance": [], "marks": [], "fees": [], "books": [], "issues": [], "next_id": 1}

def load():
    if not os.path.exists(DATA_FILE):
        return empty_data()
    f = None
    try:
        f = open(DATA_FILE, "r")
        return json.load(f)
    except json.JSONDecodeError:
        raise StorageError("data.json is damaged.")
    except OSError:
        raise StorageError("data.json could not be read.")
    finally:
        if f:
            f.close()


def save(data):
    f = None
    try:
        f = open(DATA_FILE, "w")
        json.dump(data, f, indent=2)
    except OSError:
        raise StorageError("data.json could not be saved.")
    finally:
        if f:
            f.close()


def new_id(data):
    i = data["next_id"]
    data["next_id"] += 1
    return i

# Value helpers:
def find(items, item_id):
    return next((x for x in items if x["id"] == item_id), None)


def get_or_404(items, item_id, what):
    item = find(items, item_id)
    if not item:
        raise NotFoundError(f"{what} not found.")
    return item


def to_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def clean(value):
    value = str(value or "").strip()
    return value or None

# Main Functions:
# ---------- students ----------
def students_sorted(data, department=None):
    students = data["students"]
    if department:
        students = [s for s in students if s.get("department") == department]
    return sorted(students, key=lambda s: s["roll_no"])


def departments(data):
    return sorted({s["department"] for s in data["students"] if s.get("department")})


def check_student_fields(d, other_rolls):
    roll = str(d.get("roll_no", "")).strip()
    name = str(d.get("name", "")).strip()
    if not roll or not name:
        raise ValidationError("Roll number and name are required.")
    if roll in other_rolls:
        raise ConflictError("A student with this roll number already exists.")
    return roll, name


def create_student(d):
    data = load()
    roll, name = check_student_fields(d, {s["roll_no"] for s in data["students"]})
    student = {
        "id": new_id(data), "roll_no": roll, "name": name, "email": clean(d.get("email")),
        "department": clean(d.get("department")), "year": to_int(d.get("year")),
    }
    data["students"].append(student)
    save(data)
    return student


def update_student(sid, d):
    data = load()
    student = get_or_404(data["students"], sid, "Student")
    roll, name = check_student_fields(d, {s["roll_no"] for s in data["students"] if s["id"] != sid})
    student.update(
        roll_no=roll, name=name, email=clean(d.get("email")),
        department=clean(d.get("department")), year=to_int(d.get("year")),
    )
    save(data)
    return student


def remove_student(sid):
    data = load()
    get_or_404(data["students"], sid, "Student")

    data["students"] = [s for s in data["students"] if s["id"] != sid]
    for table in ("attendance", "marks", "fees", "issues"):
        data[table] = [r for r in data[table] if r["student_id"] != sid]
    save(data)
    return {"deleted": sid}


def import_students(raw):
    try:
        reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
        headers = [(h or "").strip().lower().replace(" ", "_") for h in (reader.fieldnames or [])]
        if "roll_no" not in headers or "name" not in headers:
            raise ValidationError("The CSV must have 'Roll no' and 'Name' columns.")
        data = load()
        rolls = {s["roll_no"] for s in data["students"]}
        added, skipped = 0, []
        for line, row in enumerate(reader, start=2):
            row = {(k or "").strip().lower().replace(" ", "_"): v for k, v in row.items() if isinstance(v, str)}
            try:
                roll, name = check_student_fields(row, rolls)
            except ERPError as error:
                skipped.append(f"line {line} ({row.get('roll_no') or 'no roll no'}): {error}")
                continue
            data["students"].append({
                "id": new_id(data), "roll_no": roll, "name": name, "email": clean(row.get("email")),
                "department": clean(row.get("department")), "year": to_int(row.get("year")),
            })
            rolls.add(roll)
            added += 1
    except (UnicodeDecodeError, csv.Error):
        raise ValidationError("Could not read the file. Save it as a CSV (UTF-8) and try again.")
    if added:
        save(data)
    return added, skipped


# ---------- attendance ----------
def mark_attendance(d):
    if not all(str(d.get(f, "")).strip() for f in ("student_id", "date", "status")):
        raise ValidationError("student_id, date and status are required.")
    if d["status"] not in ("Present", "Absent"):
        raise ValidationError("Status must be Present or Absent.")
    day = parse_date(d["date"])
    data = load()
    sid = to_int(d["student_id"])
    get_or_404(data["students"], sid, "Student")

    record = next((r for r in data["attendance"] if r["student_id"] == sid and r["date"] == day), None)
    if record:
        record["status"] = d["status"]
    else:
        data["attendance"].append({"id": new_id(data), "student_id": sid, "date": day, "status": d["status"]})
    save(data)
    return {"student_id": sid, "date": day, "status": d["status"]}


def attendance_summary(data, department=None):
    rows = []
    for s in students_sorted(data, department):
        mine = [r for r in data["attendance"] if r["student_id"] == s["id"]]
        present = sum(1 for r in mine if r["status"] == "Present")
        rows.append({
            "student_id": s["id"], "roll_no": s["roll_no"], "name": s["name"], "department": s.get("department"),
            "present": present, "total": len(mine),
            "percent": round(present * 100 / len(mine)) if mine else None,
        })
    return rows


# chart colours
CHART_GOOD, CHART_WARN, CHART_BAD, CHART_MUTED = "#17692f", "#8a5300", "#b42318", "#5d6b7a"


def attendance_chart_png(department=None):
    rows = [r for r in attendance_summary(load(), department) if r["percent"] is not None]
    if not rows:
        raise NotFoundError("No attendance has been marked yet, so there is nothing to chart.")

    labels = [r["name"].split()[0] + "\n" + r["roll_no"] for r in rows]
    percents = [r["percent"] for r in rows]
    colors = [CHART_GOOD if p >= 75 else CHART_BAD for p in percents]

    fig, ax = plt.subplots(figsize=(8, 4.2))
    bars = ax.bar(labels, percents, color=colors)
    ax.bar_label(bars, fmt="%d%%")
    ax.axhline(75, linestyle="--", color=CHART_MUTED, linewidth=1, label="75% minimum")
    ax.legend(loc="upper right", frameon=False)
    ax.set_ylim(0, 120)
    ax.set_yticks(range(0, 101, 20))
    ax.set_ylabel("Attendance (%)")
    ax.set_title("Attendance by student" + (f" ({department})" if department else ""))
    fig.tight_layout()

    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", dpi=110)
    plt.close(fig)
    return buffer.getvalue()


# ---------- marks ----------
def grade_for(percent):
    for limit, grade in ((90, "A+"), (80, "A"), (70, "B"), (60, "C"), (50, "D")):
        if percent >= limit:
            return grade
    return "F"


def percent_of(m):
    return m["marks"] * 100 / m["max_marks"]


def distinct(data, field):
    seen = {}
    for m in data["marks"]:
        seen.setdefault(m[field].lower(), m[field])
    return sorted(seen.values(), key=str.lower)


def filter_marks(data, subject=None, exam=None, low=None, high=None):
    result = []
    for m in data["marks"]:
        percent = percent_of(m)
        if subject and m["subject"].lower() != subject.lower():
            continue
        if exam and m["exam"].lower() != exam.lower():
            continue
        if low is not None and percent < low:
            continue
        if high is not None and percent > high:
            continue
        result.append(m)
    return result


def filter_label(subject, exam, low, high):
    parts = []
    if subject:
        parts.append(subject)
    if exam:
        parts.append(exam)
    if low is not None and high is not None:
        parts.append(f"{low:g}% to {high:g}%")
    elif low is not None:
        parts.append(f"{low:g}% and above")
    elif high is not None:
        parts.append(f"{high:g}% and below")
    return ", ".join(parts)


def marks_with_students(data, subject=None, exam=None, low=None, high=None):
    rows = []
    for m in filter_marks(data, subject, exam, low, high):
        s = find(data["students"], m["student_id"])
        percent = round(percent_of(m), 1)
        rows.append({**m, "student_name": s["name"], "roll_no": s["roll_no"],
                     "percent": percent, "grade": grade_for(percent)})
    rows.sort(key=lambda r: (r["roll_no"], r["exam"], r["subject"]))
    return rows


def marks_summary(data, subject=None, exam=None, low=None, high=None):
    entries = filter_marks(data, subject, exam, low, high)
    rows = []
    for s in students_sorted(data):
        mine = [percent_of(m) for m in entries if m["student_id"] == s["id"]]
        if mine:
            average = round(sum(mine) / len(mine), 1)
            rows.append({"student_id": s["id"], "roll_no": s["roll_no"], "name": s["name"],
                         "department": s.get("department"), "entries": len(mine),
                         "average": average, "grade": grade_for(average)})
    return rows


def marks_chart_png(subject=None, exam=None, low=None, high=None):
    rows = marks_summary(load(), subject, exam, low, high)
    label = filter_label(subject, exam, low, high)
    if not rows:
        raise NotFoundError("No marks match this filter, so there is nothing to chart." if label
                            else "No marks have been saved yet, so there is nothing to chart.")

    labels = [r["name"].split()[0] + "\n" + r["roll_no"] for r in rows]
    averages = [r["average"] for r in rows]

    colors = [CHART_GOOD if a >= 70 else CHART_WARN if a >= 50 else CHART_BAD for a in averages]

    fig, ax = plt.subplots(figsize=(8, 4.2))
    bars = ax.bar(labels, averages, color=colors)
    ax.bar_label(bars, labels=[f"{r['average']:g}% ({r['grade']})" for r in rows])
    ax.axhline(50, linestyle="--", color=CHART_MUTED, linewidth=1, label="50% pass mark")
    ax.legend(loc="upper right", frameon=False)
    ax.set_ylim(0, 120)
    ax.set_yticks(range(0, 101, 20))
    ax.set_ylabel("Average marks (%)")
    ax.set_title("Average marks by student" + (f" ({label})" if label else ""))
    fig.tight_layout()

    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", dpi=110)
    plt.close(fig)
    return buffer.getvalue()


def save_marks(d):
    if not all(str(d.get(f, "")).strip() for f in ("student_id", "subject", "exam", "marks")):
        raise ValidationError("Student, subject, exam and marks are required.")
    try:
        obtained = float(d["marks"])
        maximum = float(d.get("max_marks") or 100)
    except ValueError:
        raise ValidationError("Marks must be numbers.")
    if maximum <= 0:
        raise ValidationError("Maximum marks must be greater than zero.")
    if not 0 <= obtained <= maximum:
        raise ValidationError("Marks must be between 0 and the maximum marks.")
    data = load()
    sid = to_int(d["student_id"])
    get_or_404(data["students"], sid, "Student")
    subject, exam = d["subject"].strip(), d["exam"].strip()

    record = next((m for m in data["marks"] if m["student_id"] == sid
                   and m["subject"].lower() == subject.lower() and m["exam"].lower() == exam.lower()), None)
    if record:
        record.update(marks=obtained, max_marks=maximum)
    else:
        record = {"id": new_id(data), "student_id": sid, "subject": subject, "exam": exam,
                  "marks": obtained, "max_marks": maximum}
        data["marks"].append(record)
    save(data)
    return record


def remove_marks(mid):
    data = load()
    get_or_404(data["marks"], mid, "Marks entry")
    data["marks"] = [m for m in data["marks"] if m["id"] != mid]
    save(data)
    return {"deleted": mid}


# ---------- fees ----------
def fees_with_students(data):
    rows = []
    for f in sorted(data["fees"], key=lambda f: f["id"], reverse=True):
        s = find(data["students"], f["student_id"])
        rows.append({**f, "student_name": s["name"], "roll_no": s["roll_no"]})
    return rows


def create_fee(d):
    if not all(str(d.get(f, "")).strip() for f in ("student_id", "description", "amount")):
        raise ValidationError("Student, description and amount are required.")
    try:
        amount = float(d["amount"])
    except ValueError:
        raise ValidationError("Amount must be a number.")
    if amount <= 0:
        raise ValidationError("Amount must be greater than zero.")
    due = clean(d.get("due_date"))
    due = parse_date(due) if due else None
    data = load()
    sid = to_int(d["student_id"])
    get_or_404(data["students"], sid, "Student")
    fee = {
        "id": new_id(data), "student_id": sid, "description": d["description"].strip(),
        "amount": amount, "due_date": due, "status": "Pending", "paid_on": None,
    }
    data["fees"].append(fee)
    save(data)
    return fee


def pay_fee(fid):
    data = load()
    fee = get_or_404(data["fees"], fid, "Fee record")
    fee["status"] = "Paid"
    fee["paid_on"] = today_str()
    save(data)
    return fee


def remove_fee(fid):
    data = load()
    get_or_404(data["fees"], fid, "Fee record")
    data["fees"] = [f for f in data["fees"] if f["id"] != fid]
    save(data)
    return {"deleted": fid}


# ---------- library ----------
def books_with_available(data):
    rows = []
    for b in sorted(data["books"], key=lambda b: b["title"].lower()):
        out = sum(1 for i in data["issues"] if i["book_id"] == b["id"] and i["return_date"] is None)
        rows.append({**b, "available": b["copies"] - out})
    return rows


def issues_with_names(data):
    rows = []
    for i in data["issues"]:
        book = find(data["books"], i["book_id"])
        student = find(data["students"], i["student_id"])
        rows.append({**i, "title": book["title"], "student_name": student["name"], "roll_no": student["roll_no"]})
    rows.sort(key=lambda r: (r["return_date"] is not None, -r["id"]))
    return rows


def create_book(d):
    if not str(d.get("title", "")).strip():
        raise ValidationError("Title is required.")
    copies = to_int(d.get("copies") or 1)
    if copies is None:
        raise ValidationError("Copies must be a whole number.")
    if copies < 1:
        raise ValidationError("Copies must be at least 1.")
    data = load()
    book = {"id": new_id(data), "title": d["title"].strip(), "author": d.get("author"), "copies": copies}
    data["books"].append(book)
    save(data)
    return book


def remove_book(bid):
    data = load()
    get_or_404(data["books"], bid, "Book")
    data["books"] = [b for b in data["books"] if b["id"] != bid]
    data["issues"] = [i for i in data["issues"] if i["book_id"] != bid]
    save(data)
    return {"deleted": bid}


def issue_book(d):
    if not all(str(d.get(f, "")).strip() for f in ("book_id", "student_id")):
        raise ValidationError("Book and student are required.")
    data = load()
    book = next((b for b in books_with_available(data) if b["id"] == to_int(d["book_id"])), None)
    if not book:
        raise NotFoundError("Book not found.")
    sid = to_int(d["student_id"])
    get_or_404(data["students"], sid, "Student")
    if book["available"] < 1:
        raise ConflictError("No copies of this book are available.")
    issue = {
        "id": new_id(data), "book_id": book["id"], "student_id": sid,
        "issue_date": today_str(), "return_date": None,
    }
    data["issues"].append(issue)
    save(data)
    return issue


def return_issue(iid):
    data = load()
    issue = find(data["issues"], iid)
    if not issue or issue["return_date"] is not None:
        raise NotFoundError("Issue not found or already returned.")
    issue["return_date"] = today_str()
    save(data)
    return {"returned": iid}


# ---------- CSV export ----------
def csv_response(filename, header, rows):
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(header)
    writer.writerows(rows)
    return Response(
        out.getvalue(), mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


# Error handler: ERPError to a JSON error (API)
@app.errorhandler(ERPError)
def handle_erp_error(error):
    if request.path.startswith("/api/"):
        return jsonify({"error": str(error)}), error.status
    return render_template("error.html", message=str(error)), error.status

# ==== APIs ====
# 1. API routes (JSON): GET and POST
def body():
    return request.get_json(silent=True) or {}


def department_arg():
    return request.args.get("department") or None


def number_arg(name):
    value = request.args.get(name, "").strip()
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        raise ValidationError("Minimum and maximum percentage must be numbers.")


def date_arg():
    day, month, year = (request.args.get(k, "").strip() for k in ("day", "month", "year"))
    if day and month and year:
        return clamp_to_month(f"{day}-{month}-{year}")
    return request.args.get("date", "").strip() or None


def marks_filter_args():
    return (request.args.get("subject") or None, request.args.get("exam") or None,
            number_arg("min_percent"), number_arg("max_percent"))


# students
@app.route("/api/students", methods=["GET"])
def api_list_students():
    return jsonify(students_sorted(load(), department_arg()))


@app.route("/api/students", methods=["POST"])
def api_add_student():
    return jsonify(create_student(body())), 201


@app.route("/api/students/<int:sid>", methods=["GET"])
def api_get_student(sid):
    return jsonify(get_or_404(load()["students"], sid, "Student"))


@app.route("/api/students/<int:sid>", methods=["PUT"])
def api_update_student(sid):
    return jsonify(update_student(sid, body()))


@app.route("/api/students/<int:sid>", methods=["DELETE"])
def api_delete_student(sid):
    return jsonify(remove_student(sid))


# attendance
@app.route("/api/attendance", methods=["GET"])
def api_list_attendance():
    records = load()["attendance"]
    day = request.args.get("date")
    if day:
        day = parse_date(day)
        records = [r for r in records if r["date"] == day]
    return jsonify(records)


@app.route("/api/attendance", methods=["POST"])
def api_mark_attendance():
    return jsonify(mark_attendance(body())), 201


@app.route("/api/attendance/summary", methods=["GET"])
def api_attendance_summary():
    return jsonify(attendance_summary(load(), department_arg()))


# marks
@app.route("/api/marks", methods=["GET"])
def api_list_marks():
    return jsonify(marks_with_students(load(), *marks_filter_args()))


@app.route("/api/marks", methods=["POST"])
def api_save_marks():
    return jsonify(save_marks(body())), 201


@app.route("/api/marks/summary", methods=["GET"])
def api_marks_summary():
    return jsonify(marks_summary(load(), *marks_filter_args()))


@app.route("/api/marks/<int:mid>", methods=["DELETE"])
def api_delete_marks(mid):
    return jsonify(remove_marks(mid))


# fees
@app.route("/api/fees", methods=["GET"])
def api_list_fees():
    return jsonify(fees_with_students(load()))


@app.route("/api/fees", methods=["POST"])
def api_add_fee():
    return jsonify(create_fee(body())), 201


@app.route("/api/fees/<int:fid>/pay", methods=["PUT"])
def api_pay_fee(fid):
    return jsonify(pay_fee(fid))


@app.route("/api/fees/<int:fid>", methods=["DELETE"])
def api_delete_fee(fid):
    return jsonify(remove_fee(fid))


# library
@app.route("/api/books", methods=["GET"])
def api_list_books():
    return jsonify(books_with_available(load()))


@app.route("/api/books", methods=["POST"])
def api_add_book():
    return jsonify(create_book(body())), 201


@app.route("/api/books/<int:bid>", methods=["DELETE"])
def api_delete_book(bid):
    return jsonify(remove_book(bid))


@app.route("/api/issues", methods=["GET"])
def api_list_issues():
    return jsonify(issues_with_names(load()))


@app.route("/api/issues", methods=["POST"])
def api_issue_book():
    return jsonify(issue_book(body())), 201


@app.route("/api/issues/<int:iid>/return", methods=["PUT"])
def api_return_book(iid):
    return jsonify(return_issue(iid))


# 2. Web pages
@app.template_filter("money")
def money(value):
    return f"₹{value:,.0f}" if float(value).is_integer() else f"₹{value:,.2f}"


@app.template_filter("num")
def num(value):
    return f"{value:g}"


def do(action, success_message, endpoint, **params):
    try:
        action()
    except ERPError as error:
        flash(str(error), "error")
    else:
        flash(success_message, "ok")
    return redirect(url_for(endpoint, **params))


@app.route("/")
def home():
    return redirect(url_for("page_students"))


# students
@app.route("/students", methods=["GET", "POST"])
def page_students():
    if request.method == "POST":
        return do(lambda: create_student(request.form.to_dict()), "Student added.", "page_students")
    return render_template("students.html", students=students_sorted(load()))


@app.route("/students/<int:sid>/edit", methods=["GET", "POST"])
def page_student_edit(sid):
    student = get_or_404(load()["students"], sid, "Student")
    if request.method == "POST":
        try:
            update_student(sid, request.form.to_dict())
        except ERPError as error:
            flash(str(error), "error")
            return redirect(url_for("page_student_edit", sid=sid))
        flash("Student updated.", "ok")
        return redirect(url_for("page_students"))
    return render_template("student_edit.html", s=student)


@app.route("/students/<int:sid>/delete", methods=["POST"])
def page_student_delete(sid):
    return do(lambda: remove_student(sid), "Student deleted.", "page_students")


@app.route("/students/import", methods=["POST"])
def page_students_import():
    file = request.files.get("file")
    if not file or not file.filename:
        flash("Choose a CSV file first.", "error")
        return redirect(url_for("page_students"))
    try:
        added, skipped = import_students(file.read())
    except ERPError as error:
        flash(str(error), "error")
    else:
        message = f"Imported {added} student(s)."
        if skipped:
            message += f" Skipped {len(skipped)}: " + "; ".join(skipped[:3]) + ("; ..." if len(skipped) > 3 else "")
        flash(message, "ok" if added else "error")
    return redirect(url_for("page_students"))


@app.route("/export/students.csv")
def export_students():
    rows = [[s["roll_no"], s["name"], s["email"] or "", s.get("department") or "", s["year"] or ""]
            for s in students_sorted(load())]
    return csv_response("students.csv", ["Roll no", "Name", "Email", "Department", "Year"], rows)


# attendance
@app.route("/attendance", methods=["GET", "POST"])
def page_attendance():
    if request.method == "POST":
        form = request.form.to_dict()
        try:
            day = parse_date(form.get("date", ""))
        except ERPError:
            day = None
        return do(lambda: mark_attendance(form), "Attendance saved.", "page_attendance",
                  date=day, department=form.get("department") or None)
    try:
        chosen = date_arg()
        day = parse_date(chosen) if chosen else today_str()
    except ERPError as error:
        flash(str(error), "error")
        day = today_str()
    department = department_arg()
    data = load()
    status = {r["student_id"]: r["status"] for r in data["attendance"] if r["date"] == day}
    days_in_month = calendar.monthrange(int(day[6:]), int(day[3:5]))[1]
    return render_template(
        "attendance.html", day=day, day_name=day_name(day), day_parts=day.split("-"), days=[f"{n:02d}" for n in range(1, days_in_month + 1)],
        months=[f"{n:02d}" for n in range(1, 13)], years=year_choices(day),
        prev_day=shift_day(day, -1), next_day=shift_day(day, 1),
        department=department, departments=departments(data),
        students=students_sorted(data, department), status=status,
        summary=attendance_summary(data, department),
    )


@app.route("/attendance/chart")
def page_attendance_chart():
    department = department_arg()
    data = load()
    has_data = any(r["total"] for r in attendance_summary(data, department))
    return render_template("chart.html", has_data=has_data, department=department, departments=departments(data))


@app.route("/attendance/chart.png")
def attendance_chart_image():
    return Response(attendance_chart_png(department_arg()), mimetype="image/png")


# marks
@app.route("/marks", methods=["GET", "POST"])
def page_marks():
    if request.method == "POST":
        return do(lambda: save_marks(request.form.to_dict()), "Marks saved.", "page_marks")
    data = load()
    subject, exam, low, high = marks_filter_args()
    summary = marks_summary(data, subject, exam, low, high)
    return render_template(
        "marks.html", students=students_sorted(data), subjects=distinct(data, "subject"), exams=distinct(data, "exam"),
        marks=marks_with_students(data, subject, exam, low, high), summary=summary, has_chart=bool(summary),
        subject=subject, exam=exam, min_percent=request.args.get("min_percent", ""),
        max_percent=request.args.get("max_percent", ""), filter_label=filter_label(subject, exam, low, high),
    )


@app.route("/marks/chart.png")
def marks_chart_image():
    return Response(marks_chart_png(*marks_filter_args()), mimetype="image/png")


@app.route("/marks/<int:mid>/delete", methods=["POST"])
def page_marks_delete(mid):
    return do(lambda: remove_marks(mid), "Marks entry deleted.", "page_marks")


# fees
@app.route("/fees", methods=["GET", "POST"])
def page_fees():
    if request.method == "POST":
        return do(lambda: create_fee(request.form.to_dict()), "Fee added.", "page_fees")
    data = load()
    return render_template("fees.html", students=students_sorted(data), fees=fees_with_students(data))


@app.route("/fees/<int:fid>/pay", methods=["POST"])
def page_fee_pay(fid):
    return do(lambda: pay_fee(fid), "Marked as paid.", "page_fees")


@app.route("/fees/<int:fid>/delete", methods=["POST"])
def page_fee_delete(fid):
    return do(lambda: remove_fee(fid), "Fee deleted.", "page_fees")


@app.route("/export/fees.csv")
def export_fees():
    rows = [[f["roll_no"], f["student_name"], f["description"], f["amount"], f["due_date"] or "", f["status"], f["paid_on"] or ""]
            for f in fees_with_students(load())]
    return csv_response("fees.csv", ["Roll no", "Student", "Description", "Amount", "Due date", "Status", "Paid on"], rows)


# library
@app.route("/library", methods=["GET"])
def page_library():
    data = load()
    return render_template(
        "library.html", students=students_sorted(data),
        books=books_with_available(data), issues=issues_with_names(data),
    )


@app.route("/library/books", methods=["POST"])
def page_book_add():
    return do(lambda: create_book(request.form.to_dict()), "Book added.", "page_library")


@app.route("/library/books/<int:bid>/delete", methods=["POST"])
def page_book_delete(bid):
    return do(lambda: remove_book(bid), "Book deleted.", "page_library")


@app.route("/library/issue", methods=["POST"])
def page_issue_add():
    return do(lambda: issue_book(request.form.to_dict()), "Book issued.", "page_library")


@app.route("/library/return/<int:iid>", methods=["POST"])
def page_issue_return(iid):
    return do(lambda: return_issue(iid), "Book returned.", "page_library")


if __name__ == "__main__":
    app.run(debug=True)
