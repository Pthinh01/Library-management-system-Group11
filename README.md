# Library Management System — Group 11

A Python library application with an embedded web interface and SQLite. The application source is contained in `Source_code.py`. It uses a three-layer architecture: presentation, business logic and data access.

## Run

Use Python 3.12 or later:

```sh
python -m pip install -r requirements.txt
python Source_code.py
```

Open http://127.0.0.1:8765. Keep the terminal open. Press Ctrl+C to stop.

Demo accounts: `thinh.nguyen` (librarian), `phucthinh` (member), `admin` (administrator). The demo password is `LibraryDemo!2026`.

The application creates `library.sqlite3` beside the source file. Keep this file to retain records after restarting. SQLite requires no separate database server. Images, fonts and interface resources are embedded in the Python file.

## Automated tests

```sh
python run_tests.py
```

The Python `unittest` suite contains 128 tests: 122 functional, domain and HTTP tests, plus 6 class-diagram tests. Tests use temporary databases and do not modify `library.sqlite3`. The runner exits with an error if any test fails and writes its detailed results to `test-results.txt`.

The Excel document contains 40 concise test cases in English, including manual interface and deployment checks. These are separate from the 128 automated tests. Performance, availability and usability targets require testing in the intended deployment environment.

## Codespaces

```sh
python Source_code.py --host 0.0.0.0 --port 8765
```

Open port 8765 from the Ports panel. Change the port number if necessary.

## Docker

```sh
docker build -t library-group11 .
docker run -d --name library-group11 -p 127.0.0.1:8766:8765 library-group11
```

Open http://127.0.0.1:8766.

```sh
docker stop library-group11
docker start library-group11
```

The SQLite file remains in the same container after stop/start. Removing the container also removes its database unless it has been backed up or stored on a persistent mount.

## Submission files

- `Source_code.py`: application, domain classes, database creation and interface.
- `Testing Document.xlsx`: 40 test cases in English using SQLite.
- `Dockerfile` and `requirements.txt`: runtime setup.
- `test_*.py`, `run_tests.py` and `test-results.txt`: automated tests and execution evidence.
- `task assignment.docx`: team task assignment.
- `containing evidence of tool usage.docx`: tool usage evidence.
