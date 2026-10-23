"""Small server-side bridge between the dashboard and GitHub/Discord.
Set DASHBOARD_PASSWORD, GITHUB_TOKEN, GITHUB_REPOSITORY and optionally GITHUB_BRANCH.
Never put GitHub tokens or Discord webhooks in browser code.
"""
import base64, json, os
from urllib.parse import quote
import requests
from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_from_directory

# Load local secrets from web/.env when present. Environment variables already set by the host take precedence.
load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))

app = Flask(__name__, static_folder='static', static_url_path='/static')
API = 'https://api.github.com'

def config():
    return {
        'token': os.getenv('GITHUB_TOKEN', '').strip(),
        'repo': os.getenv('GITHUB_REPOSITORY', '').strip(),
        'branch': os.getenv('GITHUB_BRANCH', 'main').strip() or 'main',
        'password': os.getenv('DASHBOARD_PASSWORD', '').strip(),
    }

def require_auth():
    c = config()
    if not c['password']:
        return jsonify({'error': 'Server setup error: DASHBOARD_PASSWORD is not configured.'}), 503
    auth = request.headers.get('Authorization', '')
    if not auth.startswith('Bearer ') or auth[7:] != c['password']:
        return jsonify({'error': 'Unauthorized. Enter your dashboard password.'}), 401
    if not c['token'] or not c['repo']:
        return jsonify({'error': 'Server setup error: GITHUB_TOKEN and GITHUB_REPOSITORY are required.'}), 503
    return None

def gh_headers():
    c = config()
    return {'Authorization': f"Bearer {c['token']}", 'Accept': 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28'}

def repo_url(path=''):
    c = config()
    base = f"{API}/repos/{c['repo']}"
    return base + ('/' + path.lstrip('/') if path else '')

def get_file(path):
    c = config()
    r = requests.get(repo_url('contents/' + path), headers=gh_headers(), params={'ref': c['branch']}, timeout=20)
    r.raise_for_status()
    payload = r.json()
    raw = base64.b64decode(payload['content']).decode('utf-8')
    return json.loads(raw), payload['sha']

def put_file(path, data, sha, message):
    c = config()
    body = {'message': message, 'content': base64.b64encode((json.dumps(data, indent=2, ensure_ascii=False) + '\n').encode()).decode(), 'sha': sha, 'branch': c['branch']}
    r = requests.put(repo_url('contents/' + path), headers=gh_headers(), json=body, timeout=20)
    if r.status_code not in (200, 201):
        return jsonify({'error': f'GitHub rejected the update ({r.status_code}): {r.text[:500]}'}), r.status_code
    return jsonify({'ok': True, 'commit': r.json().get('commit', {}).get('html_url')})

@app.get('/')
def index():
    return send_from_directory('static', 'index.html')

@app.get('/api/health')
def health():
    return jsonify({'service': 'stock-alerts-dashboard', 'configured': bool(config()['password'] and config()['token'] and config()['repo'])})

@app.get('/api/watchlist')
def watchlist_get():
    err = require_auth()
    if err: return err
    try:
        data, _ = get_file('alerts/watchlist.json')
        return jsonify(data)
    except requests.RequestException as e:
        return jsonify({'error': f'Could not read watchlist from GitHub: {e}'}), 502
    except (ValueError, KeyError) as e:
        return jsonify({'error': f'Could not parse watchlist: {e}'}), 502

@app.put('/api/watchlist')
def watchlist_put():
    err = require_auth()
    if err: return err
    data = request.get_json(silent=True)
    if not isinstance(data, dict): return jsonify({'error': 'Expected watchlist JSON object.'}), 400
    # Validate and normalize the schema without silently inventing thresholds.
    cleaned = {}
    for raw_ticker, item in data.items():
        ticker = str(raw_ticker).strip().upper()
        if not ticker or not isinstance(item, dict): return jsonify({'error': 'Each watchlist entry must be an object with a ticker.'}), 400
        prices = item.get('price_targets', [])
        vals = item.get('valuation_targets', {})
        if not isinstance(prices, list) or not isinstance(vals, dict): return jsonify({'error': f'Invalid target format for {ticker}.'}), 400
        try:
            prices = [float(x) for x in prices if str(x).strip()]
            new_vals = {}
            for metric, directions in vals.items():
                if metric not in ('FxPE', 'PE', 'P/S') or not isinstance(directions, dict): continue
                new_vals[metric] = {}
                for direction in ('trim', 'buy'):
                    arr = directions.get(direction, [])
                    if not isinstance(arr, list): raise ValueError(f'{ticker} {metric} {direction} must be a list')
                    new_vals[metric][direction] = [float(x) for x in arr if str(x).strip()]
        except (ValueError, TypeError) as e:
            return jsonify({'error': f'Invalid numeric target: {e}'}), 400
        cleaned[ticker] = {'price_targets': prices, 'valuation_targets': new_vals}
    try:
        _, sha = get_file('alerts/watchlist.json')
        return put_file('alerts/watchlist.json', cleaned, sha, 'Update watchlist from web dashboard')
    except requests.RequestException as e:
        return jsonify({'error': f'Could not update GitHub watchlist: {e}'}), 502

@app.get('/api/portfolio')
def portfolio_get():
    err = require_auth()
    if err: return err
    try:
        data, _ = get_file('portfolio/marks_portfolio.json')
        positions = []
        total_cost = 0.0
        for ticker, item in data.items():
            if ticker == 'closed_positions' or not isinstance(item, dict): continue
            shares = float(item.get('shares', 0) or 0)
            avg = float(item.get('avg_price', 0) or 0)
            cost = shares * avg
            total_cost += cost
            positions.append({'ticker': ticker, 'shares': shares, 'avg_price': avg, 'cost_basis': cost, 'realized_pl': float(item.get('realized_pl', 0) or 0)})
        positions.sort(key=lambda x: x['cost_basis'], reverse=True)
        return jsonify({'positions': positions, 'position_count': len(positions), 'total_cost_basis': total_cost, 'note': 'Cost basis from repository. Live market value is not shown unless a live quote source is configured.'})
    except requests.RequestException as e:
        return jsonify({'error': f'Could not read portfolio from GitHub: {e}'}), 502

@app.get('/api/workflows')
def workflows_get():
    err = require_auth()
    if err: return err
    c = config()
    url = repo_url('actions/runs')
    r = requests.get(url, headers=gh_headers(), params={'branch': c['branch'], 'per_page': 15}, timeout=20)
    if not r.ok: return jsonify({'error': f'GitHub Actions API error ({r.status_code}): {r.text[:400]}'}), r.status_code
    runs = []
    for x in r.json().get('workflow_runs', []):
        runs.append({'id': x.get('id'), 'name': x.get('name'), 'status': x.get('status'), 'conclusion': x.get('conclusion'), 'event': x.get('event'), 'created_at': x.get('created_at'), 'html_url': x.get('html_url'), 'path': x.get('path')})
    return jsonify(runs)

@app.post('/api/workflows/dispatch')
def workflow_dispatch():
    err = require_auth()
    if err: return err
    body = request.get_json(silent=True) or {}
    workflow = str(body.get('workflow', '')).strip()
    allowed = {'stock_checker.yml', 'watchlist_manager.yml', 'earnings_report.yml', 'economic_alert.yml', 'heartbeat.yml', 'portfolio_summary.yml'}
    if workflow not in allowed: return jsonify({'error': 'Workflow is not on the dashboard allowlist.'}), 400
    c = config()
    r = requests.post(repo_url(f'actions/workflows/{quote(workflow)}/dispatches'), headers=gh_headers(), json={'ref': c['branch']}, timeout=20)
    if r.status_code != 204: return jsonify({'error': f'GitHub could not dispatch workflow ({r.status_code}): {r.text[:400]}'}), r.status_code
    return jsonify({'ok': True, 'message': f'Dispatch requested for {workflow}. Refresh workflow history in a few seconds.'})

@app.post('/api/discord/test')
def discord_test():
    err = require_auth()
    if err: return err
    hook = os.getenv('DISCORD_STOCK_WEBHOOK', '').strip()
    if not hook: return jsonify({'error': 'DISCORD_STOCK_WEBHOOK is not configured on the dashboard server.'}), 503
    r = requests.post(hook, json={'content': '✅ Stock Alerts dashboard test: Discord webhook delivery succeeded.'}, timeout=15)
    if r.status_code not in (200, 204): return jsonify({'error': f'Discord rejected the test ({r.status_code}): {r.text[:300]}'}), 502
    return jsonify({'ok': True, 'message': 'Discord accepted the test message.'})

if __name__ == '__main__':
    # Local-only default. Use a production WSGI server when deploying.
    app.run(host='127.0.0.1', port=int(os.getenv('PORT', '8000')), debug=False)
