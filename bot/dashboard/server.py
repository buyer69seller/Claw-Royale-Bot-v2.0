from flask import Flask, render_template, jsonify
import json
import os
from datetime import datetime
from ..config import Config
from ..utils.logger import logger

app = Flask(__name__, template_folder='templates', static_folder='static')

# Status cache
bot_status = {
    "status": "running",
    "started_at": datetime.now().isoformat(),
    "games_played": 0,
    "current_game": None
}

@app.route('/')
def index():
    return render_template('dashboard.html')

@app.route('/api/status')
def status():
    return jsonify(bot_status)

@app.route('/api/config')
def config():
    return jsonify(Config.get_all())

@app.route('/api/logs')
def logs():
    try:
        log_dir = os.path.join(Config.BASE_PATH, "logs")
        log_files = sorted([f for f in os.listdir(log_dir) if f.startswith("bot_")])
        if log_files:
            with open(os.path.join(log_dir, log_files[-1]), 'r') as f:
                lines = f.readlines()
                return jsonify({"logs": lines[-100:]})
        return jsonify({"logs": []})
    except Exception as e:
        return jsonify({"error": str(e)})

@app.route('/health')
def health():
    return jsonify({"status": "healthy"})

def start_server():
    host = Config.WEB_HOST
    port = Config.WEB_PORT
    logger.info(f"🌐 Dashboard: http://{host}:{port}")
    app.run(host=host, port=port, debug=False, threaded=True)