import os
import re
import time
import json
import secrets
from datetime import datetime
from functools import wraps
from flask import Flask, request, jsonify, render_template_string, send_from_directory, Response, redirect, url_for, make_response
from flask_cors import CORS
from google.cloud import logging as cloud_logging
from query_sutta_corpus import buddha_wisdom  # Assuming this is your wisdom-seeking function
from markdown import markdown
import requests
import shutil

app = Flask(__name__)

# --- CORS Security: Restrict CORS to public endpoint /query only ---
CORS(app, resources={r"/query": {"origins": "*"}})

# --- HTTP Security Headers ---
@app.after_request
def add_security_headers(response):
    """Enforces standard security headers on all HTTP responses."""
    response.headers['X-Frame-Options'] = 'SAMEORIGIN'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    response.headers['Content-Security-Policy'] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://ipapi.co; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: https:; "
        "connect-src 'self' https://ipapi.co;"
    )
    return response

# --- Use the locally provided Dharma Wheel image ---
IMAGE_FILENAME = "dharma_wheel.png"
IMAGE_PATH = "/home/stefan_morar/512px-Dharma_Wheel_Rotating.svg.png"  # Use the path provided
STATIC_DIR = os.path.join(app.root_path, "static")
LOCAL_IMAGE_DESTINATION = os.path.join(STATIC_DIR, IMAGE_FILENAME)

# Ensure the 'static' directory exists
if not os.path.exists(STATIC_DIR):
    os.makedirs(STATIC_DIR)

# Copy the image to the static folder if it doesn't exist
if not os.path.exists(LOCAL_IMAGE_DESTINATION):
    try:
        shutil.copy(IMAGE_PATH, LOCAL_IMAGE_DESTINATION)
        print(f"Image copied successfully to {LOCAL_IMAGE_DESTINATION}")
    except FileNotFoundError:
        print(f"Error: Image not found at {IMAGE_PATH}")
    except Exception as e:
        print(f"An unexpected error occurred while copying the image: {e}")

# --- Authentication Configuration & Secure Secrets ---
ADMIN_USER = os.environ.get("ADMIN_USER")
ADMIN_PASS = os.environ.get("ADMIN_PASS")
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN")

if not ADMIN_TOKEN and not (ADMIN_USER and ADMIN_PASS):
    print("[NOTICE] Admin dashboard disabled until credentials are configured.", flush=True)

def check_auth(username, password):
    """Verifies admin credentials."""
    return bool(ADMIN_USER and ADMIN_PASS) and secrets.compare_digest(username, ADMIN_USER) and secrets.compare_digest(password, ADMIN_PASS)

def authenticate():
    """Sends a 401 response that triggers HTTP Basic Authentication."""
    return Response(
        'Access Denied: Authentication required to view Buddha\'s Wisdom Log Summary Dashboard.',
        401,
        {'WWW-Authenticate': 'Basic realm="Buddha Wisdom Log Summary Dashboard"'}
    )

def requires_auth(f):
    """Decorator to protect sensitive admin / log summary routes."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not ADMIN_TOKEN and not (ADMIN_USER and ADMIN_PASS):
            return Response('Dashboard unavailable: configure admin credentials.', 503)

        # 1. Allow secret query token access (?token=...) or header (X-Admin-Token)
        token_arg = request.args.get('token')
        token_hdr = request.headers.get('X-Admin-Token')
        if ADMIN_TOKEN and ((token_arg and secrets.compare_digest(token_arg, ADMIN_TOKEN)) or (token_hdr and secrets.compare_digest(token_hdr, ADMIN_TOKEN))):
            return f(*args, **kwargs)
        
        # 2. HTTP Basic Auth
        auth = request.authorization
        if not auth or not check_auth(auth.username, auth.password):
            return authenticate()
        return f(*args, **kwargs)
    return decorated

# --- Rate Limiting Protection ---
RATE_LIMIT_STORE = {}

def is_rate_limited(ip_address, max_requests=30, window_seconds=60):
    """Simple in-memory sliding window IP rate limiter."""
    now = time.time()
    timestamps = RATE_LIMIT_STORE.get(ip_address, [])
    valid_timestamps = [t for t in timestamps if now - t < window_seconds]
    if len(valid_timestamps) >= max_requests:
        return True
    valid_timestamps.append(now)
    RATE_LIMIT_STORE[ip_address] = valid_timestamps
    return False

# --- Local Logging Engine ---
def write_local_log(level, event_type, message, details=None):
    """Writes structured log entries to local persistent jsonl storage."""
    log_dir = os.path.join(app.root_path, "logs")
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, "app_events.jsonl")
    
    entry = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "level": level,
        "type": event_type,
        "message": message,
        "details": details or {}
    }
    try:
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception as e:
        print(f"Failed writing local log: {e}", flush=True)

def read_local_logs():
    """Reads stored local logs from app_events.jsonl."""
    log_file = os.path.join(app.root_path, "logs", "app_events.jsonl")
    if not os.path.exists(log_file):
        return []
    logs = []
    try:
        with open(log_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        logs.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
    except Exception as e:
        print(f"Error reading local log file: {e}", flush=True)
    return logs

# --- Topic Summarization Helper ---
TOPIC_KEYWORDS = {
    "Meditation & Mindfulness": [r"meditation", r"mindful", r"jhana", r"vipassana", r"breath", r"focus", r"samadhi", r"sati"],
    "Dukkha & Suffering": [r"suffering", r"dukkha", r"pain", r"sorrow", r"grief", r"stress", r"anxiety", r"desire", r"attachment"],
    "Karma & Rebirth": [r"karma", r"kamma", r"rebirth", r"reincarnation", r"action", r"samsara", r"destiny"],
    "Noble Eightfold Path & Ethics": [r"path", r"eightfold", r"precept", r"ethics", r"virtue", r"sila", r"right action", r"conduct"],
    "Nirvana & Enlightenment": [r"nirvana", r"nibbana", r"enlightenment", r"liberation", r"awakening", r"cessation", r"unconditioned"],
    "Wisdom & Four Noble Truths": [r"wisdom", r"truth", r"four noble", r"prajna", r"panna", r"dharma", r"dhamma", r"understanding"],
    "Compassion & Loving-Kindness": [r"compassion", r"karuna", r"metta", r"loving-kindness", r"love", r"kindness", r"empathy"],
    "Impermanence & Non-Self": [r"impermanence", r"anicca", r"anatta", r"non-self", r"no self", r"change", r"emptiness"]
}

def analyze_topics(queries):
    """Categorizes queries into Buddha teaching topics for summary analytics."""
    topic_counts = {t: 0 for t in TOPIC_KEYWORDS}
    for q in queries:
        q_lower = q.lower()
        for topic, keywords in TOPIC_KEYWORDS.items():
            if any(re.search(kw, q_lower) for kw in keywords):
                topic_counts[topic] += 1
    
    sorted_topics = sorted(topic_counts.items(), key=lambda x: x[1], reverse=True)
    total = len(queries)
    result = []
    for name, count in sorted_topics:
        pct = round((count / total * 100), 1) if total > 0 else 0.0
        result.append({"name": name, "count": count, "pct": pct})
    return result

def fetch_cloud_logs():
    """Fetches log entries from GCP Cloud Logging if available."""
    try:
        project_id = os.environ.get("GOOGLE_CLOUD_PROJECT", "rag-projects-451405")
        client = cloud_logging.Client(project=project_id)
        filter_str = (
            'resource.type="cloud_run_revision" AND '
            'resource.labels.service_name="buddha-wisdom"'
        )
        entries = client.list_entries(filter_=filter_str, page_size=200, max_results=500)
        logs = []
        metric_pattern = re.compile(r"\[METRIC\] Query:\s*'(.*?)'\s*\|\s*Country:\s*(.*)")
        for entry in entries:
            payload = entry.payload if isinstance(entry.payload, str) else str(entry.payload)
            timestamp_str = entry.timestamp.strftime("%Y-%m-%d %H:%M:%S") if entry.timestamp else "N/A"
            match = metric_pattern.search(payload)
            if match:
                query_text = match.group(1)
                country = match.group(2).strip()
                logs.append({
                    "timestamp": timestamp_str,
                    "level": "INFO",
                    "type": "METRIC",
                    "message": f"Query: '{query_text}' | Country: {country}",
                    "details": {
                        "query": query_text,
                        "country": country,
                        "latency_ms": 0,
                        "status": 200
                    }
                })
            else:
                level = getattr(entry, 'severity', 'INFO') or 'INFO'
                logs.append({
                    "timestamp": timestamp_str,
                    "level": level,
                    "type": "SYSTEM",
                    "message": payload[:250],
                    "details": {"raw": payload}
                })
        return logs
    except Exception as e:
        print(f"GCP Cloud Logging fetch notice: {e}", flush=True)
        return []

def get_summarized_logs():
    """Combines local and cloud logs, generating full summary metrics and topic analysis."""
    local_logs = read_local_logs()
    cloud_logs = fetch_cloud_logs()
    
    seen = set()
    combined = []
    for l in local_logs + cloud_logs:
        key = (l.get("timestamp"), l.get("message"))
        if key not in seen:
            seen.add(key)
            combined.append(l)
            
    combined.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
    
    total_queries = 0
    total_errors = 0
    latencies = []
    country_counts = {}
    timeline_counts = {}
    level_counts = {"METRIC": 0, "INFO": 0, "ERROR": 0, "SYSTEM": 0}
    queries_list = []

    for item in combined:
        lvl = item.get("level", "INFO").upper()
        event_type = item.get("type", "SYSTEM")
        
        if event_type == "METRIC":
            level_counts["METRIC"] = level_counts.get("METRIC", 0) + 1
        elif lvl in level_counts:
            level_counts[lvl] += 1
        else:
            level_counts["INFO"] = level_counts.get("INFO", 0) + 1
            
        details = item.get("details", {})
        status = details.get("status")
        if lvl == "ERROR" or status == 500:
            total_errors += 1
            
        query_text = details.get("query")
        if query_text:
            total_queries += 1
            queries_list.append(query_text)
            
            country = details.get("country", "Unknown")
            country_counts[country] = country_counts.get(country, 0) + 1
            
            lat = details.get("latency_ms")
            if lat:
                try:
                    latencies.append(float(lat))
                except (ValueError, TypeError):
                    pass

        ts = item.get("timestamp", "")
        date_str = ts.split(" ")[0] if " " in ts else ""
        if date_str and date_str != "N/A":
            timeline_counts[date_str] = timeline_counts.get(date_str, 0) + 1

    avg_latency = round(sum(latencies) / len(latencies), 1) if latencies else "N/A"
    success_rate = round(((total_queries - total_errors) / total_queries * 100), 1) if total_queries > 0 else 100.0
    topic_summary = analyze_topics(queries_list)
    
    sorted_timeline = dict(sorted(timeline_counts.items())[-14:])
    
    return {
        "total_logs": len(combined),
        "total_queries": total_queries,
        "total_errors": total_errors,
        "success_rate": success_rate,
        "avg_latency": avg_latency,
        "unique_countries": len(country_counts),
        "country_counts": country_counts,
        "timeline_counts": sorted_timeline,
        "level_counts": level_counts,
        "topic_summary": topic_summary,
        "recent_logs": combined[:200]
    }

# --- Serve the static image ---
@app.route("/static/<path:filename>")
def serve_static(filename):
    """Serves static files from the 'static' directory safely."""
    return send_from_directory("static", filename)

# Enhanced HTML template with Markdown support, loading animation, DOM XSS protection, and Buddhist styling
chat_template = """
<!DOCTYPE html>
<html>
<head>
    <title>Buddha's Wisdom Chat</title>
    <style>
        body {
            font-family: 'Times New Roman', serif;
            background-color: #f8f0e3;
            color: #5c4033;
            margin: 0;
            display: flex;
            flex-direction: column;
            min-height: 100vh;
        }
        h1 {
            text-align: center;
            color: #8b4513;
            padding: 20px;
            background-color: #f0e6d2;
            margin: 0;
        }
        #chatbox {
            border: 2px solid #d2b48c;
            padding: 20px;
            margin: 20px;
            flex-grow: 1;
            overflow-y: auto;
            background-color: #fffaf0;
            border-radius: 10px;
            box-shadow: 0 4px 8px rgba(0, 0, 0, 0.1);
        }
        .message {
            margin-bottom: 15px;
            padding: 10px;
            border-radius: 8px;
        }
        .user {
            color: #2e8b57;
            background-color: #e0f0e0;
            text-align: right;
        }
        .buddha {
            color: #8b4513;
            background-color: #f5f5dc;
            text-align: left;
        }
        .error {
            color: #cc0000;
            background-color: #ffe0e0;
        }
        p {
            margin-bottom: 10px;
            line-height: 1.6;
        }
        em, i {
            font-style: italic;
        }
        strong, b {
            font-weight: bold;
        }
        h1, h2, h3, h4, h5, h6 {
            margin-top: 1em;
            margin-bottom: 0.5em;
            color: #8b4513;
        }
        pre {
            background-color: #f0f0f0;
            padding: 10px;
            overflow-x: auto;
            border-radius: 5px;
        }
        code {
            font-family: monospace;
        }
        blockquote {
            border-left: 5px solid #d2b48c;
            padding-left: 15px;
            margin-left: 0;
            font-style: italic;
        }
        #loading {
            display: none;
            text-align: center;
            margin-top: 20px;
        }
        .dharma-wheel-container {
            display: inline-block;
            width: 60px;
            height: 60px;
            position: relative;
        }
        .dharma-wheel {
            position: absolute;
            width: 100%;
            height: 100%;
            animation: rotate 10s linear infinite;
        }
        @keyframes rotate {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }
        input[type="text"] {
            width: calc(100% - 100px);
            padding: 10px;
            margin: 20px;
            border: 1px solid #d2b48c;
            border-radius: 5px;
            font-size: 16px;
        }
        button {
            padding: 10px 20px;
            background-color: #8b4513;
            color: white;
            border: none;
            border-radius: 5px;
            cursor: pointer;
            font-size: 16px;
        }
        button:hover {
            background-color: #a0522d;
        }
        html, body {
            height: 100%;
        }
        #chatbox {
            height: calc(100vh - 150px);
            margin: 20px auto;
            width: 90%;
            max-width: 1200px;
        }
        .message strong {
            color: #8b4513;
        }
        .passage-results {
            margin-top: 18px;
            border-top: 1px solid #d2b48c;
            padding-top: 12px;
        }
        .passage-results summary { cursor: pointer; font-weight: bold; }
        .passage-item {
            margin-top: 10px;
            padding: 10px;
            border: 1px solid #d2b48c;
            border-radius: 6px;
            background: #fffaf0;
        }
        .passage-item pre {
            max-height: 420px;
            overflow-y: auto;
            white-space: pre-wrap;
            overflow-wrap: anywhere;
            font: inherit;
            line-height: 1.5;
            background: transparent;
            padding: 0;
        }
        .passage-item a { display: inline-block; margin-top: 8px; }
        .more-passages { margin-top: 12px; }
    </style>
</head>
<body>
    <h1>Buddha's Wisdom Chat</h1>
    <div id="chatbox">
        <div class="message buddha"><strong>Buddha:</strong> Welcome! Ask me anything about the Dharma.</div>
    </div>
    <div id="loading">
        <div class="dharma-wheel-container">
            <img class="dharma-wheel" src="/static/{{ image_filename }}" alt="Dharma Wheel">
        </div>
        <p>Seeking wisdom...</p>
    </div>
    <input type="text" id="inputBox" placeholder="Type your question here..." />
    <button id="sendButton">Send</button>

    <script>
        document.addEventListener('DOMContentLoaded', function() {
            const inputBox = document.getElementById('inputBox');
            const sendButton = document.getElementById('sendButton');
            const chatbox = document.getElementById('chatbox');
            const loading = document.getElementById('loading');

            let userCountry = "Unknown";
            fetch("https://ipapi.co/json/")
                .then(response => response.json())
                .then(data => {
                    if (data && data.country_name) {
                        userCountry = data.country_name;
                    }
                })
                .catch(err => {
                    console.warn("Could not determine user location:", err);
                });

            function appendPassages(message, passages) {
                if (!Array.isArray(passages) || passages.length === 0) return;
                const section = document.createElement('details');
                section.className = 'passage-results';
                const title = document.createElement('summary');
                title.textContent = `${passages.length} matching PDF excerpts from the suttas`;
                section.appendChild(title);
                const list = document.createElement('div');
                section.appendChild(list);
                const more = document.createElement('button');
                more.type = 'button';
                more.className = 'more-passages';
                more.textContent = 'Show 10 more';
                let shown = 0;

                function showNext() {
                    for (const passage of passages.slice(shown, shown + 10)) {
                        const item = document.createElement('details');
                        item.className = 'passage-item';
                        const heading = document.createElement('summary');
                        const [first, last] = passage.pdf_pages;
                        const page = first === last ? `p. ${first}` : `pp. ${first}-${last}`;
                        heading.textContent = `${passage.source} · PDF ${page}`;
                        item.appendChild(heading);
                        if (passage.sutta_reference) {
                            const link = document.createElement('a');
                            const slug = passage.sutta_reference.toLowerCase().split(' ').join('');
                            link.href = `https://suttacentral.net/${slug}/en/sujato`;
                            link.target = '_blank';
                            link.rel = 'noopener noreferrer';
                            link.textContent = `Read ${passage.sutta_reference} on SuttaCentral`;
                            item.appendChild(link);
                        }
                        const excerpt = document.createElement('pre');
                        excerpt.textContent = passage.text;
                        item.appendChild(excerpt);
                        list.appendChild(item);
                    }
                    shown = Math.min(shown + 10, passages.length);
                    more.hidden = shown >= passages.length;
                }

                more.addEventListener('click', showNext);
                section.addEventListener('toggle', () => {
                    if (section.open && shown === 0) {
                        showNext();
                        section.appendChild(more);
                    }
                });
                message.appendChild(section);
            }

            function sendMessage() {
                const message = inputBox.value.trim();
                if (message === "" || sendButton.disabled) return;
                inputBox.value = "";

                // DOM XSS Safe Rendering
                const userMsg = document.createElement('div');
                userMsg.classList.add('message', 'user');
                const userLabel = document.createElement('strong');
                userLabel.textContent = "You: ";
                userMsg.appendChild(userLabel);
                userMsg.appendChild(document.createTextNode(message));
                chatbox.appendChild(userMsg);
                chatbox.scrollTop = chatbox.scrollHeight;

                loading.style.display = "block";
                sendButton.disabled = true;
                const controller = new AbortController();
                const timeout = setTimeout(() => controller.abort(), 150000);

                fetch("/query", {
                    method: "POST",
                    headers: {
                        "Content-Type": "application/json"
                    },
                    body: JSON.stringify({
                        query: message,
                        country: userCountry
                    }),
                    signal: controller.signal
                })
                .then(async response => {
                    const data = await response.json();
                    if (!response.ok) {
                        throw new Error(data.error || "The answer service is unavailable. Please try again.");
                    }
                    if (!data.response) {
                        throw new Error("The answer service returned an empty reply. Please try again.");
                    }
                    return data;
                })
                .then(data => {
                    const botMsg = document.createElement('div');
                    botMsg.classList.add('message', 'buddha');
                    botMsg.innerHTML = "<strong>Buddha:</strong> " + data.response;
                    appendPassages(botMsg, data.passages);
                    chatbox.appendChild(botMsg);
                    chatbox.scrollTop = chatbox.scrollHeight;
                })
                .catch(error => {
                    console.error("Error:", error);
                    const errorMsg = document.createElement('div');
                    errorMsg.classList.add('message', 'error');
                    errorMsg.textContent = error.name === "AbortError"
                        ? "This answer is taking too long. Please try again."
                        : error.message || "I encountered an error. Please try again.";
                    chatbox.appendChild(errorMsg);
                    chatbox.scrollTop = chatbox.scrollHeight;
                })
                .finally(() => {
                    clearTimeout(timeout);
                    loading.style.display = "none";
                    sendButton.disabled = false;
                });
            }

            sendButton.addEventListener("click", sendMessage);

            inputBox.addEventListener("keypress", function(event) {
                if (event.key === "Enter") {
                    event.preventDefault();
                    sendMessage();
                }
            });
        });
    </script>
</body>
</html>
"""

@app.route("/", methods=['GET'])
def index():
    """Serves the enhanced chat interface."""
    return render_template_string(chat_template, image_filename=IMAGE_FILENAME)

@app.route("/query", methods=['POST'])
def query():
    """Handles user queries, enforces rate limiting, input validation, and logs events."""
    start_time = time.time()
    
    # 1. IP Rate Limiting Check
    client_ip = request.remote_addr or "unknown"
    if is_rate_limited(client_ip):
        write_local_log("WARNING", "RATE_LIMIT", f"Rate limit exceeded for IP {client_ip}", {"ip": client_ip})
        return jsonify({'error': 'Too many requests. Please wait a moment before trying again.'}), 429

    # 2. Input Validation
    data = request.get_json(silent=True) or {}
    user_query = data.get('query')
    country = data.get('country', 'Unknown')
    
    if not user_query or not isinstance(user_query, str) or not user_query.strip():
        return jsonify({'error': 'No valid query provided'}), 400

    # Truncate to max 1000 characters
    user_query = user_query.strip()[:1000]

    print(f"[METRIC] Query: '{user_query}' | Country: {country}", flush=True)
    try:
        response, passages = buddha_wisdom(user_query, include_passages=True)
        html_response = markdown(response)
        elapsed_ms = round((time.time() - start_time) * 1000, 1)

        write_local_log(
            level="INFO",
            event_type="METRIC",
            message=f"Query: '{user_query}' | Country: {country}",
            details={
                "query": user_query,
                "country": country,
                "latency_ms": elapsed_ms,
                "status": 200
            }
        )
        return jsonify({'response': html_response, 'passages': passages})
    except Exception as e:
        elapsed_ms = round((time.time() - start_time) * 1000, 1)
        print(f"Error in /query: {e}", flush=True)
        write_local_log(
            level="ERROR",
            event_type="ERROR",
            message=f"Error in /query: {str(e)}",
            details={
                "query": user_query,
                "country": country,
                "latency_ms": elapsed_ms,
                "status": 500,
                "error": str(e)
            }
        )
        return jsonify({'error': "The answer service is temporarily unavailable. Please try again."}), 503

# --- Private Log Summary Dashboard Template ---
log_summary_template = """<!DOCTYPE html>
<html>
<head>
    <title>Buddha's Wisdom — Private Log Summary Dashboard</title>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        :root {
            --bg-color: #fcf8f2;
            --card-bg: rgba(255, 255, 255, 0.85);
            --primary: #8b4513;
            --accent: #d2b48c;
            --text-dark: #3a2e26;
            --border-color: rgba(210, 180, 140, 0.4);
            --success: #2e7d32;
            --error: #c62828;
            --metric: #1565c0;
        }
        body {
            font-family: 'Times New Roman', Georgia, serif;
            background-color: var(--bg-color);
            color: var(--text-dark);
            margin: 0;
            padding: 30px 20px;
        }
        .container {
            max-width: 1300px;
            margin: 0 auto;
        }
        .header-bar {
            display: flex;
            justify-content: space-between;
            align-items: center;
            background: linear-gradient(135deg, #8b4513, #5c2c0c);
            color: #fffaf0;
            padding: 25px 35px;
            border-radius: 18px;
            margin-bottom: 30px;
            box-shadow: 0 10px 30px rgba(92, 44, 12, 0.2);
        }
        .header-title h1 {
            margin: 0 0 5px 0;
            font-size: 2.2em;
            font-weight: 400;
            letter-spacing: 1px;
        }
        .header-title p {
            margin: 0;
            font-size: 0.95em;
            opacity: 0.85;
            font-style: italic;
        }
        .badge-private {
            background-color: #ffd700;
            color: #4a2800;
            padding: 6px 14px;
            border-radius: 20px;
            font-weight: bold;
            font-size: 0.85em;
            text-transform: uppercase;
            letter-spacing: 1px;
        }
        .grid-kpi {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }
        .kpi-card {
            background: var(--card-bg);
            border: 1px solid var(--border-color);
            border-radius: 16px;
            padding: 25px;
            text-align: center;
            box-shadow: 0 6px 20px rgba(139, 69, 19, 0.05);
            transition: transform 0.2s ease;
        }
        .kpi-card:hover {
            transform: translateY(-3px);
        }
        .kpi-val {
            font-size: 3.2em;
            color: var(--primary);
            font-weight: 300;
            margin: 8px 0;
        }
        .kpi-lbl {
            font-size: 0.9em;
            text-transform: uppercase;
            letter-spacing: 1.5px;
            color: #7a6352;
            font-weight: 600;
        }
        .kpi-sub {
            font-size: 0.85em;
            color: #8c7665;
            margin-top: 5px;
        }
        .grid-charts {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 25px;
            margin-bottom: 30px;
        }
        @media (max-width: 900px) {
            .grid-charts {
                grid-template-columns: 1fr;
            }
        }
        .card {
            background: var(--card-bg);
            border: 1px solid var(--border-color);
            border-radius: 16px;
            padding: 25px;
            box-shadow: 0 6px 20px rgba(139, 69, 19, 0.05);
        }
        .card h3 {
            margin-top: 0;
            color: var(--primary);
            border-bottom: 2px solid var(--accent);
            padding-bottom: 10px;
            font-size: 1.3em;
        }
        .chart-container {
            position: relative;
            height: 280px;
            width: 100%;
        }
        .topic-list {
            list-style: none;
            padding: 0;
            margin: 15px 0 0 0;
        }
        .topic-item {
            margin-bottom: 12px;
        }
        .topic-header {
            display: flex;
            justify-content: space-between;
            font-size: 0.95em;
            margin-bottom: 4px;
        }
        .topic-bar-bg {
            background: rgba(210, 180, 140, 0.3);
            border-radius: 8px;
            height: 10px;
            overflow: hidden;
        }
        .topic-bar-fill {
            background: linear-gradient(90deg, #8b4513, #cd853f);
            height: 100%;
            border-radius: 8px;
        }
        .controls-bar {
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 15px;
            margin-bottom: 20px;
        }
        .search-box {
            padding: 10px 16px;
            border: 1px solid var(--accent);
            border-radius: 8px;
            font-size: 1em;
            width: 280px;
            background: #fff;
        }
        .filter-select {
            padding: 10px 16px;
            border: 1px solid var(--accent);
            border-radius: 8px;
            font-size: 0.95em;
            background: #fff;
            color: var(--text-dark);
        }
        .btn-action {
            background-color: var(--primary);
            color: white;
            border: none;
            padding: 10px 18px;
            border-radius: 8px;
            cursor: pointer;
            font-size: 0.9em;
            text-decoration: none;
            display: inline-block;
            transition: background-color 0.2s ease;
        }
        .btn-action:hover {
            background-color: #a0522d;
        }
        table {
            width: 100%;
            border-collapse: collapse;
            margin-top: 15px;
        }
        th, td {
            text-align: left;
            padding: 12px 15px;
            border-bottom: 1px solid rgba(210, 180, 140, 0.2);
            font-size: 0.95em;
        }
        th {
            background-color: rgba(240, 230, 210, 0.6);
            color: var(--primary);
            font-weight: 600;
        }
        tr:hover {
            background-color: rgba(255, 255, 255, 0.6);
        }
        .badge-lvl {
            padding: 3px 8px;
            border-radius: 12px;
            font-size: 0.75em;
            font-weight: bold;
            text-transform: uppercase;
        }
        .badge-metric { background-color: #e3f2fd; color: #1565c0; }
        .badge-info { background-color: #e8f5e9; color: #2e7d32; }
        .badge-error { background-color: #ffebee; color: #c62828; }
        .badge-country { background-color: #f3e5f5; color: #6a1b9a; }
        
        .json-preview {
            display: none;
            background: #272822;
            color: #f8f8f2;
            padding: 10px;
            border-radius: 6px;
            font-family: monospace;
            font-size: 0.85em;
            white-space: pre-wrap;
            margin-top: 8px;
        }
    </style>
</head>
<body>
    <div class="container">
        <!-- Private Header -->
        <div class="header-bar">
            <div class="header-title">
                <h1>Buddha's Wisdom — Private Log Summary</h1>
                <p>Authenticated Admin Feed • Aggregate System & Query Metrics</p>
            </div>
            <div>
                <span class="badge-private">🔒 Private Access Only</span>
            </div>
        </div>

        <!-- KPI Cards -->
        <div class="grid-kpi">
            <div class="kpi-card">
                <div class="kpi-lbl">Total Queries</div>
                <div class="kpi-val">{{ data.total_queries }}</div>
                <div class="kpi-sub">All-time recorded</div>
            </div>

            <div class="kpi-card">
                <div class="kpi-lbl">Success Rate</div>
                <div class="kpi-val" style="color: {{ 'var(--success)' if data.success_rate > 95 else 'var(--error)' }};">{{ data.success_rate }}%</div>
                <div class="kpi-sub">{{ data.total_errors }} total errors</div>
            </div>

            <div class="kpi-card">
                <div class="kpi-lbl">Unique Regions</div>
                <div class="kpi-val">{{ data.unique_countries }}</div>
                <div class="kpi-sub">Countries detected</div>
            </div>

            <div class="kpi-card">
                <div class="kpi-lbl">Avg Response Latency</div>
                <div class="kpi-val" style="font-size: 2.6em;">{{ data.avg_latency }}{{ 'ms' if data.avg_latency != 'N/A' else '' }}</div>
                <div class="kpi-sub">Query processing speed</div>
            </div>
        </div>

        <!-- Analytics Row 1 -->
        <div class="grid-charts">
            <div class="card">
                <h3>Geographic Distribution</h3>
                <div class="chart-container">
                    <canvas id="geoChart"></canvas>
                </div>
            </div>

            <div class="card">
                <h3>14-Day Query Activity Timeline</h3>
                <div class="chart-container">
                    <canvas id="timelineChart"></canvas>
                </div>
            </div>
        </div>

        <!-- Analytics Row 2: Topic Summarizer -->
        <div class="grid-charts">
            <div class="card">
                <h3>Query Topic Breakdown</h3>
                <p style="font-size: 0.85em; color: #666; margin-top: -5px;">Automatic keyword categorization across user questions</p>
                <ul class="topic-list">
                    {% for topic in data.topic_summary %}
                    <li class="topic-item">
                        <div class="topic-header">
                            <span><strong>{{ topic.name }}</strong></span>
                            <span>{{ topic.count }} queries ({{ topic.pct }}%)</span>
                        </div>
                        <div class="topic-bar-bg">
                            <div class="topic-bar-fill" style="width: {{ topic.pct }}%;"></div>
                        </div>
                    </li>
                    {% endfor %}
                </ul>
            </div>

            <div class="card">
                <h3>Log Severity Breakdown</h3>
                <div class="chart-container">
                    <canvas id="severityChart"></canvas>
                </div>
            </div>
        </div>

        <!-- Filterable Log Table Explorer -->
        <div class="card" style="margin-bottom: 40px;">
            <div class="controls-bar">
                <h3 style="margin: 0; border: none; padding: 0;">Recent Log Entries ({{ data.recent_logs | length }})</h3>
                <div style="display: flex; gap: 10px;">
                    <input type="text" id="searchInput" class="search-box" placeholder="Search logs by query or origin..." onkeyup="filterLogs()">
                    <select id="severityFilter" class="filter-select" onchange="filterLogs()">
                        <option value="ALL">All Levels</option>
                        <option value="METRIC">METRIC</option>
                        <option value="INFO">INFO</option>
                        <option value="ERROR">ERROR</option>
                    </select>
                    <a href="/admin/logs/export?format=csv" class="btn-action">📥 Export CSV</a>
                    <a href="/admin/logs/export?format=json" class="btn-action" style="background-color: #4a3c31;">📄 Export JSON</a>
                </div>
            </div>

            {% if data.recent_logs %}
            <table id="logTable">
                <thead>
                    <tr>
                        <th>Timestamp</th>
                        <th>Level</th>
                        <th>Type</th>
                        <th>User Query / Message</th>
                        <th>Origin</th>
                        <th>Latency</th>
                        <th>Details</th>
                    </tr>
                </thead>
                <tbody>
                    {% for log in data.recent_logs %}
                    <tr class="log-row" data-level="{{ log.level }}" data-text="{{ (log.message ~ ' ' ~ (log.details.query | default('')) ~ ' ' ~ (log.details.country | default(''))) | lower }}">
                        <td>{{ log.timestamp }}</td>
                        <td>
                            <span class="badge-lvl badge-{{ log.level | lower }}">{{ log.level }}</span>
                        </td>
                        <td><strong>{{ log.type }}</strong></td>
                        <td>
                            {% if log.details.query %}
                                "{{ log.details.query }}"
                            {% else %}
                                {{ log.message }}
                            {% endif %}
                        </td>
                        <td>
                            {% if log.details.country %}
                                <span class="badge-lvl badge-country">{{ log.details.country }}</span>
                            {% else %}
                                -
                            {% endif %}
                        </td>
                        <td>
                            {% if log.details.latency_ms %}
                                {{ log.details.latency_ms }} ms
                            {% else %}
                                -
                            {% endif %}
                        </td>
                        <td>
                            <button class="btn-action" style="padding: 3px 8px; font-size: 0.8em;" onclick="toggleJson('json-{{ loop.index }}')">View Raw</button>
                            <div id="json-{{ loop.index }}" class="json-preview">{{ log | tojson(indent=2) }}</div>
                        </td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
            {% else %}
            <p style="text-align: center; color: #8b4513; margin-top: 30px;">No logs recorded yet. Perform queries to populate real-time analytics!</p>
            {% endif %}
        </div>
    </div>

    <script>
        document.addEventListener('DOMContentLoaded', function() {
            // Geographic Doughnut Chart
            const geoCtx = document.getElementById('geoChart').getContext('2d');
            const countryCounts = {{ data.country_counts | tojson }};
            new Chart(geoCtx, {
                type: 'doughnut',
                data: {
                    labels: Object.keys(countryCounts),
                    datasets: [{
                        data: Object.values(countryCounts),
                        backgroundColor: ['#8b4513', '#a0522d', '#cd853f', '#d2b48c', '#deb887', '#f4a460', '#e9967a', '#ff9966', '#d3a625', '#8fbc8f']
                    }]
                },
                options: { responsive: true, maintainAspectRatio: false }
            });

            // Timeline Bar Chart
            const timeCtx = document.getElementById('timelineChart').getContext('2d');
            const timelineCounts = {{ data.timeline_counts | tojson }};
            new Chart(timeCtx, {
                type: 'bar',
                data: {
                    labels: Object.keys(timelineCounts),
                    datasets: [{
                        label: 'Queries',
                        data: Object.values(timelineCounts),
                        backgroundColor: '#8b4513',
                        borderRadius: 6
                    }]
                },
                options: { responsive: true, maintainAspectRatio: false, scales: { y: { beginAtZero: true } } }
            });

            // Severity Breakdown Pie Chart
            const sevCtx = document.getElementById('severityChart').getContext('2d');
            const levelCounts = {{ data.level_counts | tojson }};
            new Chart(sevCtx, {
                type: 'pie',
                data: {
                    labels: Object.keys(levelCounts),
                    datasets: [{
                        data: Object.values(levelCounts),
                        backgroundColor: ['#1565c0', '#2e7d32', '#c62828', '#8b4513']
                    }]
                },
                options: { responsive: true, maintainAspectRatio: false }
            });
        });

        function filterLogs() {
            const query = document.getElementById('searchInput').value.toLowerCase();
            const severity = document.getElementById('severityFilter').value;
            const rows = document.querySelectorAll('.log-row');

            rows.forEach(row => {
                const text = row.getAttribute('data-text');
                const level = row.getAttribute('data-level');
                const matchesSearch = text.includes(query);
                const matchesSeverity = (severity === 'ALL' || level === severity);

                if (matchesSearch && matchesSeverity) {
                    row.style.display = '';
                } else {
                    row.style.display = 'none';
                }
            });
        }

        function toggleJson(id) {
            const el = document.getElementById(id);
            if (el.style.display === 'block') {
                el.style.display = 'none';
            } else {
                el.style.display = 'block';
            }
        }
    </script>
</body>
</html>"""

@app.route("/admin/logs", methods=['GET'])
@requires_auth
def admin_logs():
    """Renders the protected Log Summary Dashboard."""
    try:
        summary_data = get_summarized_logs()
    except Exception as e:
        print(f"Error fetching log summary: {e}", flush=True)
        summary_data = {
            "total_logs": 0, "total_queries": 0, "total_errors": 0,
            "success_rate": 0, "avg_latency": "N/A", "unique_countries": 0,
            "country_counts": {}, "timeline_counts": {}, "level_counts": {},
            "topic_summary": [], "recent_logs": [], "error": str(e)
        }
    return render_template_string(log_summary_template, data=summary_data)

@app.route("/dashboard", methods=['GET'])
@requires_auth
def dashboard():
    """Protected alias route for dashboard redirecting to /admin/logs."""
    return admin_logs()

@app.route("/admin/logs/export", methods=['GET'])
@requires_auth
def export_logs():
    """Exports logs as CSV or JSON."""
    export_format = request.args.get("format", "json").lower()
    summary = get_summarized_logs()
    logs = summary.get("recent_logs", [])
    
    if export_format == "csv":
        import io
        import csv
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["Timestamp", "Level", "Type", "Query", "Country", "Latency_ms", "Status", "Error"])
        for l in logs:
            det = l.get("details", {})
            writer.writerow([
                l.get("timestamp", ""),
                l.get("level", ""),
                l.get("type", ""),
                det.get("query", ""),
                det.get("country", ""),
                det.get("latency_ms", ""),
                det.get("status", ""),
                det.get("error", "")
            ])
        response = make_response(output.getvalue())
        response.headers["Content-Disposition"] = "attachment; filename=buddha_wisdom_logs.csv"
        response.headers["Content-Type"] = "text/csv"
        return response
    else:
        response = make_response(jsonify(logs))
        response.headers["Content-Disposition"] = "attachment; filename=buddha_wisdom_logs.json"
        response.headers["Content-Type"] = "application/json"
        return response

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
