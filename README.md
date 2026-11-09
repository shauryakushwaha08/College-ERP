# College ERP (Mini Project)

Flask (Python) backend, HTML/CSS pages, and a JSON file for storage. No database, no JavaScript.
Modules: Students (CRUD), Attendance, Marks, Fees, Library.

## Run

```bash
pip install -r requirements.txt
python app.py
```

Open http://127.0.0.1:5000

## Files

- `app.py` - the whole backend: custom exceptions, JSON storage, logic, REST API routes (`/api/...`) and web page routes
- `templates/` - HTML pages
- `static/style.css` - styling
- `data.json` - stored data

## APIs

| Module | Routes |
|---|---|
| Students | GET, POST `/api/students` - GET, PUT, DELETE `/api/students/<id>` |
| Attendance | GET, POST `/api/attendance` - GET `/api/attendance/summary` |
| Marks | GET, POST `/api/marks` - GET `/api/marks/summary` - DELETE `/api/marks/<id>` |
| Fees | GET, POST `/api/fees` - PUT `/api/fees/<id>/pay` - DELETE `/api/fees/<id>` |
| Library | GET, POST `/api/books` - DELETE `/api/books/<id>` - GET, POST `/api/issues` - PUT `/api/issues/<id>/return` |


Status codes: 200 OK, 201 Created, 400 bad input, 404 not found, 409 conflict, 500 data file problem.
