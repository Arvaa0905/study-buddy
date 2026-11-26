#!/bin/sh
set -eu

echo "Initializing Study Buddy database..."
python - <<'PY'
import os
import time
from app import init_db, app

max_attempts = int(os.getenv("DB_WAIT_ATTEMPTS", "30"))
delay = float(os.getenv("DB_WAIT_DELAY", "2"))

for attempt in range(1, max_attempts + 1):
    try:
        init_db()
        app.logger.info("Database is ready.")
        break
    except Exception as exc:
        if attempt == max_attempts:
            app.logger.error("Database initialization failed after %s attempts: %s", max_attempts, exc)
            raise
        app.logger.warning("Waiting for database (attempt %s/%s)...", attempt, max_attempts)
        time.sleep(delay)
PY

exec "$@"

