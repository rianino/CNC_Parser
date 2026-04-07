"""Web app for vectorization file analysis and email reporting."""

from __future__ import annotations

import html
import logging
import os
import re
import shutil
import smtplib
import sys
import tempfile
import threading
import time
import webbrowser
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request
from werkzeug.utils import secure_filename

# Ensure hitex_tool is importable regardless of how we're launched
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from hitex_tool.production import auto_detect, to_dict  # noqa: E402

# Load .env if present (local dev); in production env vars are set by the host
load_dotenv(Path(__file__).resolve().parent / ".env", override=False)

logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024  # 50 MB
app.secret_key = os.getenv("SECRET_KEY", os.urandom(32))

# Use /tmp for uploads — works in Docker, serverless, and local
UPLOAD_DIR = Path(tempfile.gettempdir()) / "vetorizacao_uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8080"))

ALLOWED_EXTENSIONS = {".zip", ".brt"}
_EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")

# Rate limiting: track email sends per IP
_email_rate: dict[str, list[float]] = {}
_EMAIL_RATE_LIMIT = 10  # max emails per window
_EMAIL_RATE_WINDOW = 3600  # 1 hour


# ---------- Security headers ----------

@app.after_request
def _security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "0"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src https://fonts.gstatic.com; "
        "script-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; "
        "connect-src 'self'"
    )
    return response


# ---------- Helpers ----------

def _allowed_file(filename: str) -> bool:
    name = filename.lower()
    return any(name.endswith(ext) for ext in ALLOWED_EXTENSIONS)


def _validate_email(email: str) -> bool:
    """Strict email validation — single address, no header injection."""
    if not email or len(email) > 254:
        return False
    if "\r" in email or "\n" in email:
        return False
    return bool(_EMAIL_RE.match(email))


def _check_email_rate(ip: str) -> bool:
    """Return True if the IP is within the rate limit."""
    now = time.time()
    times = _email_rate.get(ip, [])
    times = [t for t in times if now - t < _EMAIL_RATE_WINDOW]
    if len(times) >= _EMAIL_RATE_LIMIT:
        _email_rate[ip] = times
        return False
    times.append(now)
    _email_rate[ip] = times
    return True


def _sanitize_for_header(value: str) -> str:
    """Strip any characters that could be used for header injection."""
    return re.sub(r"[\r\n\x00]", "", value)[:200]


# ---------- Routes ----------

@app.route("/")
def index():
    smtp_configured = bool(os.getenv("SMTP_HOST"))
    return render_template("index.html", smtp_configured=smtp_configured)


@app.route("/analyse", methods=["POST"])
def analyse():
    """Upload and analyse a vectorization file."""
    if "file" not in request.files:
        return jsonify({"error": "Nenhum ficheiro enviado"}), 400

    f = request.files["file"]
    if not f.filename or not _allowed_file(f.filename):
        return jsonify({"error": "Tipo de ficheiro invalido. Usar .zop.zip ou .brt"}), 400

    # Sanitize filename to prevent path traversal
    safe_name = secure_filename(f.filename)
    if not safe_name or not _allowed_file(safe_name):
        return jsonify({"error": "Nome de ficheiro invalido"}), 400

    tmp_dir = tempfile.mkdtemp(dir=UPLOAD_DIR)
    file_path = Path(tmp_dir) / safe_name

    # Verify resolved path is inside tmp_dir (belt-and-suspenders)
    if not str(file_path.resolve()).startswith(str(Path(tmp_dir).resolve())):
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return jsonify({"error": "Nome de ficheiro invalido"}), 400

    f.save(file_path)

    try:
        pd = auto_detect(file_path)
        result = to_dict(pd)
        return jsonify(result)
    except Exception:
        logger.exception("Error processing file %s", safe_name)
        return jsonify({"error": "Erro ao processar ficheiro. Verificar que o formato e valido."}), 500
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


@app.route("/send-email", methods=["POST"])
def send_email():
    """Send production data by email."""
    data = request.get_json()
    if not data:
        return jsonify({"error": "Dados em falta"}), 400

    recipient = data.get("email", "").strip()
    production_data = data.get("production_data")

    if not _validate_email(recipient):
        return jsonify({"error": "Endereco de email invalido"}), 400
    if not production_data or not isinstance(production_data, dict):
        return jsonify({"error": "Dados de producao em falta"}), 400

    # Rate limiting
    client_ip = request.remote_addr or "unknown"
    if not _check_email_rate(client_ip):
        return jsonify({"error": "Limite de envios atingido. Tentar mais tarde."}), 429

    smtp_host = os.getenv("SMTP_HOST", "")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER", "")
    smtp_pass = os.getenv("SMTP_PASS", "")
    smtp_from = os.getenv("SMTP_FROM", smtp_user)

    if not smtp_host or not smtp_user:
        return jsonify({"error": "SMTP nao configurado. Contactar administrador."}), 500

    # Sanitize values that enter email headers
    source_file = _sanitize_for_header(str(production_data.get("source_file", "ficheiro")))
    subject = f"Dados de Producao — {source_file}"

    html_body = _build_email_html(production_data)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = smtp_from
    msg["To"] = recipient
    msg.attach(MIMEText(html_body, "html"))

    try:
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_from, [recipient], msg.as_string())
        return jsonify({"ok": True, "message": f"Email enviado para {recipient}"})
    except Exception:
        logger.exception("SMTP send failed for %s", recipient)
        return jsonify({"error": "Erro ao enviar email. Contactar administrador."}), 500


# ---------- Email HTML builder ----------

def _esc(value) -> str:
    """HTML-escape a value for safe insertion into email template."""
    return html.escape(str(value))


def _esc_colour(hex_val: str | None) -> str:
    """Validate and return a safe CSS colour value."""
    if not hex_val or not re.match(r"^#[0-9a-fA-F]{6}$", hex_val):
        return "#cccccc"
    return hex_val


def _build_email_html(pd: dict) -> str:
    """Build a clean HTML email with production data."""
    dims = pd.get("dimensions", {})
    totals = pd.get("totals", {})
    colours = pd.get("colours", [])

    colour_rows = ""
    for c in colours:
        safe_hex = _esc_colour(c.get("colour_hex"))
        colour_rows += f"""
        <tr>
            <td style="padding: 10px 14px; border-bottom: 1px solid #e4e4e7;">
                <span style="display:inline-block;width:14px;height:14px;border-radius:3px;background:{safe_hex};vertical-align:middle;margin-right:8px;border:1px solid #d4d4d8;"></span>
                {_esc(c.get('name', ''))}
            </td>
            <td style="padding: 10px 14px; border-bottom: 1px solid #e4e4e7; text-align:right; font-variant-numeric: tabular-nums;">{float(c.get('area_m2', 0)):.4f} m2</td>
            <td style="padding: 10px 14px; border-bottom: 1px solid #e4e4e7; text-align:right; font-variant-numeric: tabular-nums;">{float(c.get('percentage', 0)):.1f}%</td>
            <td style="padding: 10px 14px; border-bottom: 1px solid #e4e4e7; text-align:right; font-variant-numeric: tabular-nums;">{float(c.get('tuft_length_m', 0)):.1f} m</td>
            <td style="padding: 10px 14px; border-bottom: 1px solid #e4e4e7; text-align:right; font-variant-numeric: tabular-nums;">{int(c.get('stitch_count', 0)):,}</td>
            <td style="padding: 10px 14px; border-bottom: 1px solid #e4e4e7;">{_esc(c.get('loop_cut_mode', '')) or '\u2014'}</td>
        </tr>"""

    source_file = _esc(pd.get("source_file", ""))
    source_type = _esc(pd.get("source_type", ""))

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="margin:0; padding:0; background:#f4f4f5; font-family: -apple-system, 'Segoe UI', sans-serif;">
<div style="max-width:680px; margin:32px auto; background:#ffffff; border-radius:8px; border:1px solid #e4e4e7; overflow:hidden;">

    <div style="padding:28px 32px 20px; border-bottom:1px solid #e4e4e7;">
        <h1 style="margin:0 0 4px; font-size:20px; font-weight:700; color:#18181b; letter-spacing:-0.02em;">Dados de Producao</h1>
        <p style="margin:0; font-size:14px; color:#71717a;">{source_file} &middot; {source_type.upper()}</p>
    </div>

    <div style="padding:20px 32px; display:flex; gap:32px; border-bottom:1px solid #e4e4e7;">
        <div>
            <p style="margin:0 0 2px; font-size:12px; color:#71717a; text-transform:uppercase; letter-spacing:0.05em;">Dimensoes</p>
            <p style="margin:0; font-size:16px; font-weight:600; color:#18181b;">{float(dims.get('width_m', 0)):.3f} x {float(dims.get('height_m', 0)):.3f} m</p>
        </div>
        <div>
            <p style="margin:0 0 2px; font-size:12px; color:#71717a; text-transform:uppercase; letter-spacing:0.05em;">Area Total</p>
            <p style="margin:0; font-size:16px; font-weight:600; color:#18181b;">{float(totals.get('design_area_m2', 0)):.4f} m2</p>
        </div>
        <div>
            <p style="margin:0 0 2px; font-size:12px; color:#71717a; text-transform:uppercase; letter-spacing:0.05em;">Comprimento Tuft</p>
            <p style="margin:0; font-size:16px; font-weight:600; color:#18181b;">{float(totals.get('tuft_length_m', 0)):.1f} m</p>
        </div>
        <div>
            <p style="margin:0 0 2px; font-size:12px; color:#71717a; text-transform:uppercase; letter-spacing:0.05em;">Cores</p>
            <p style="margin:0; font-size:16px; font-weight:600; color:#18181b;">{int(totals.get('colour_count', 0))}</p>
        </div>
    </div>

    <table style="width:100%; border-collapse:collapse; font-size:14px; color:#18181b;">
        <thead>
            <tr style="background:#fafafa;">
                <th style="padding:10px 14px; text-align:left; font-weight:600; font-size:12px; text-transform:uppercase; letter-spacing:0.05em; color:#71717a; border-bottom:2px solid #e4e4e7;">Cor</th>
                <th style="padding:10px 14px; text-align:right; font-weight:600; font-size:12px; text-transform:uppercase; letter-spacing:0.05em; color:#71717a; border-bottom:2px solid #e4e4e7;">Area</th>
                <th style="padding:10px 14px; text-align:right; font-weight:600; font-size:12px; text-transform:uppercase; letter-spacing:0.05em; color:#71717a; border-bottom:2px solid #e4e4e7;">%</th>
                <th style="padding:10px 14px; text-align:right; font-weight:600; font-size:12px; text-transform:uppercase; letter-spacing:0.05em; color:#71717a; border-bottom:2px solid #e4e4e7;">Comprimento</th>
                <th style="padding:10px 14px; text-align:right; font-weight:600; font-size:12px; text-transform:uppercase; letter-spacing:0.05em; color:#71717a; border-bottom:2px solid #e4e4e7;">Pontos</th>
                <th style="padding:10px 14px; text-align:left; font-weight:600; font-size:12px; text-transform:uppercase; letter-spacing:0.05em; color:#71717a; border-bottom:2px solid #e4e4e7;">Modo</th>
            </tr>
        </thead>
        <tbody>
            {colour_rows}
        </tbody>
    </table>

    <div style="padding:16px 32px; background:#fafafa; border-top:1px solid #e4e4e7;">
        <p style="margin:0; font-size:12px; color:#a1a1aa;">Gerado automaticamente pela ferramenta de analise de vetorizacao SRTAP</p>
    </div>

</div>
</body>
</html>"""


def run():
    """Production entry point."""
    from waitress import serve

    print()
    print("  Analise de Vetorizacao — SRTAP")
    print(f"  http://{HOST}:{PORT}")
    print()

    # Open browser only when running locally (not in Docker)
    if os.getenv("DOCKER") is None and HOST in ("127.0.0.1", "localhost"):
        threading.Timer(1.0, lambda: webbrowser.open(f"http://127.0.0.1:{PORT}")).start()

    serve(app, host=HOST, port=PORT, threads=4)


if __name__ == "__main__":
    run()
