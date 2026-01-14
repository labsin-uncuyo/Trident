from flask import Flask, Response, request
import logging
import os
import json
from datetime import datetime

app = Flask(__name__)

EXPECTED_USER = os.environ.get("LOGIN_USER", "admin")
EXPECTED_PASS = os.environ.get("LOGIN_PASSWORD") or os.environ.get("LAB_PASSWORD", "admin123")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("login_app")

# Login attempts log file
LOGIN_LOG_FILE = "/tmp/flask_login_attempts.jsonl"

LOGIN_FORM = """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <title>Lab Login</title>
  </head>
  <body>
    <h1>Lab Login</h1>
    <form method="post" action="/login">
      <label>Username <input name="username" /></label><br />
      <label>Password <input name="password" type="password" /></label><br />
      <button type="submit">Sign in</button>
    </form>
  </body>
</html>
"""


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return Response(LOGIN_FORM, mimetype="text/html")

    username = request.form.get("username", "")
    password = request.form.get("password", "")
    remote = request.remote_addr or "unknown"

    # Log this attempt to JSONL file
    attempt_data = {
        "timestamp": datetime.utcnow().isoformat(),
        "username": username,
        "password_len": len(password),
        "remote_addr": remote,
        "success": username == EXPECTED_USER and password == EXPECTED_PASS
    }

    try:
        with open(LOGIN_LOG_FILE, "a") as f:
            f.write(json.dumps(attempt_data) + "\n")
    except Exception as e:
        logger.error("Failed to write login attempt log: %s", e)

    if username == EXPECTED_USER and password == EXPECTED_PASS:
        logger.info("login ok user=%s from=%s", username, remote)
        return "OK\n", 200

    logger.warning("login failed user=%s pass_len=%d from=%s", username, len(password), remote)
    return "Invalid credentials\n", 401


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=443)
