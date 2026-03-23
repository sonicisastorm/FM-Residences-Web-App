"""
run.py — FM Residences
Entry point for the application.

Dev:        python run.py
Production: waitress-serve --host=0.0.0.0 --port=8000 run:app
"""

from src import create_app

app = create_app()

if __name__ == "__main__":
    # Development server only — use waitress or gunicorn in production
    app.run(
        host="0.0.0.0",
        port=5000,
        debug=True   # Set False in production (or control via FLASK_ENV)
    )