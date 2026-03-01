# =============================================================================
# Aria Blue - Dashboard Portal
# Flask app with GraphQL, Grid, Search for Aria activities and records
# =============================================================================

from flask import Flask, render_template, make_response, request, Response, send_from_directory, jsonify, redirect
from flask_wtf.csrf import CSRFProtect
import os
import time
import logging
import requests as http_requests

_logger = logging.getLogger("aria.web")

def create_app():
    app = Flask(__name__,
                template_folder='templates',
                static_folder='static')
    
    app.config['SECRET_KEY'] = os.environ['SECRET_KEY']

    # S-17: Secure session cookies in production
    _is_production = os.environ.get('FLASK_ENV', 'development').lower() == 'production'
    app.config['SESSION_COOKIE_SECURE'] = _is_production
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

    # S-17: CSRF protection
    csrf = CSRFProtect(app)

    service_host = os.environ['SERVICE_HOST']
    api_base_url = os.environ['API_BASE_URL']
    # REMOVED: legacy bot proxy config (Operation Independence)

    # Internal API service URL (Docker network or localhost fallback)
    _api_int_port = os.environ.get('API_INTERNAL_PORT', '8000')
    _api_internal_url = os.environ.get('API_INTERNAL_URL', f'http://aria-api:{_api_int_port}')
    _api_key = os.environ.get('ARIA_API_KEY', '')
    _admin_key = os.environ.get('ARIA_ADMIN_KEY', '')
    # WebSocket base URL (browser-accessible) — used for WS chat connections
    _ws_base_url = os.environ.get('WS_BASE_URL', '')
    # Host-exposed API port (for browser-side WS fallback)
    _api_port = os.environ.get('ARIA_API_PORT', '8000')
    # LiteLLM external port (for browser-side model router link)
    _litellm_port = os.environ.get('LITELLM_PORT', '18793')

    # Computed once at startup — used as ?v= cache-buster for static assets
    _build_ts = int(time.time())

    @app.context_processor
    def inject_config():
        return {
            'service_host': service_host,
            'api_base_url': api_base_url,
            'ws_base_url': _ws_base_url,
            'ws_api_key': _api_key,
            'api_port': _api_port,
            'litellm_port': _litellm_port,
            'build_ts': _build_ts,
            # REMOVED: legacy bot proxy config
        }
    
    @app.after_request
    def add_header(response):
        # Disable Chrome's speculative loading that causes prefetch storms
        response.headers['Supports-Loading-Mode'] = 'fenced-frame'

        # Force fresh dashboard HTML to avoid stale templates/scripts after deploys
        if response.content_type and response.content_type.startswith('text/html'):
            response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
            response.headers['Pragma'] = 'no-cache'
            response.headers['Expires'] = '0'
        return response

    @app.route('/favicon.ico')
    def favicon_ico():
        return send_from_directory(app.static_folder, 'favicon.svg', mimetype='image/svg+xml')
    
    # =========================================================================
    # API Reverse Proxy - forwards /api/* to aria-api backend
    # Enables dashboard to work when accessed directly (port 5000)
    # without requiring Traefik (port 80)
    # =========================================================================
    @app.route('/api/', defaults={'path': ''}, methods=['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS'])
    @app.route('/api/<path:path>', methods=['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS'])
    def api_proxy(path):
        """S-27: API reverse proxy with proper error handling."""
        url = f"{_api_internal_url}/{path}"
        try:
            upstream_headers = {
                k: v for k, v in request.headers
                if k.lower() not in ('host', 'transfer-encoding')
            }
            if 'X-API-Key' not in upstream_headers:
                if path.startswith('admin/') and _admin_key:
                    upstream_headers['X-API-Key'] = _admin_key
                elif _api_key:
                    upstream_headers['X-API-Key'] = _api_key

            resp = http_requests.request(
                method=request.method,
                url=url,
                params=request.args,
                headers=upstream_headers,
                data=request.get_data(),
                timeout=30,
            )
            # Build Flask response from upstream
            excluded_headers = {'content-encoding', 'transfer-encoding', 'connection', 'content-length'}
            headers = {k: v for k, v in resp.headers.items() if k.lower() not in excluded_headers}
            return Response(resp.content, status=resp.status_code, headers=headers)
        except http_requests.exceptions.ConnectionError:
            _logger.error("API proxy connection error: cannot reach %s", url)
            return jsonify({
                "error": "API service unavailable",
                "detail": "Cannot connect to the Aria API backend. Is aria-api running?",
            }), 502
        except http_requests.exceptions.Timeout:
            _logger.error("API proxy timeout: %s", url)
            return jsonify({
                "error": "API request timed out",
                "detail": "The API backend did not respond within 30 seconds.",
            }), 504
        except Exception as e:
            _logger.error("API proxy unexpected error: %s — %s", url, e)
            return jsonify({
                "error": "Proxy error",
                "detail": str(e)[:200],
            }), 500

    # Exempt API reverse proxy from CSRF checks (JSON API pass-through endpoint)
    csrf.exempt(api_proxy)

    # REMOVED: legacy bot proxy route (Operation Independence)
    # Previously: forwarded to legacy bot service with Bearer token injection
    # Replaced by: native /chat/ route (S6-01) connecting to engine WebSocket

    # Legacy redirect: anyone bookmarking /clawdbot/ gets redirected to /chat/
    @app.route('/clawdbot/')
    @app.route('/clawdbot/<path:path>')
    def legacy_bot_redirect(path=''):
        from flask import redirect
        return redirect('/chat/', code=301)

    # =========================================================================
    # Routes - Pages
    # =========================================================================
    
    @app.route('/')
    def index():
        return render_template('index.html')
    
    @app.route('/dashboard')
    def dashboard():
        from flask import redirect
        return redirect('/', code=301)
    
    @app.route('/activities')
    def activities():
        return render_template('activities.html')

    @app.route('/activity-visualization')
    @app.route('/creative-pulse')
    def creative_pulse():
        return render_template('creative_pulse.html')
    
    @app.route('/thoughts')
    def thoughts():
        return render_template('thoughts.html')
    
    @app.route('/memories')
    def memories():
        return render_template('memories.html')

    @app.route('/memory-graph')
    def memory_graph():
        return render_template('memory_graph.html')

    @app.route('/memory-search')
    def memory_search():
        return render_template('memory_search.html')

    @app.route('/memory-timeline')
    def memory_timeline():
        return render_template('memory_timeline.html')

    @app.route('/memory-dashboard')
    def memory_dashboard():
        return render_template('memory_consolidation.html')

    @app.route('/embedding-explorer')
    def embedding_explorer():
        return render_template('embedding_explorer.html')

    @app.route('/lessons')
    def lessons_page():
        return render_template('lessons.html')

    @app.route('/sentiment')
    def sentiment():
        return render_template('sentiment.html')

    @app.route('/patterns')
    def patterns():
        return render_template('patterns.html')

    @app.route('/records')
    def records():
        return render_template('records.html')
    
    @app.route('/search')
    def search():
        # Removed — redirect to memories
        return redirect('/memories', code=301)
    
    @app.route('/services')
    def services():
        dynamic_host = request.host.split(':')[0]
        service_layers = [
            {
                'title': '🌐 External Access',
                'services': [
                    {
                        'id': 'traefik',
                        'name': 'Traefik',
                        'icon': '🔀',
                        'port': ':80/:443',
                        'href': '/traefik/dashboard/',
                        'target': '_blank',
                    },
                    {
                        'id': 'aria-engine',
                        'name': 'Aria Chat',
                        'icon': '💬',
                        'port': 'Native',
                        'href': '/chat/',
                    },
                    {
                        'id': 'litellm',
                        'name': 'LiteLLM',
                        'icon': '⚡',
                        'port': f":{_litellm_port}",
                        'href': '/models',
                        'control': True,
                        'control_note': 'Router',
                    },
                ],
            },
            {
                'title': '🐳 Docker Core Services',
                'services': [
                    {
                        'id': 'aria-web',
                        'name': 'aria-web',
                        'icon': '🌐',
                        'port': 'Flask :5000',
                        'href': '/',
                        'control': True,
                        'control_note': 'Flask UI',
                    },
                    {
                        'id': 'aria-api',
                        'name': 'aria-api',
                        'icon': '🚀',
                        'port': 'FastAPI :8000',
                        'href': '/api/docs',
                        'target': '_blank',
                        'control': True,
                        'control_note': 'FastAPI',
                    },
                ],
            },
            {
                'title': '🧠 LLM Backends',
                'services': [
                    {
                        'id': 'mlx',
                        'name': 'MLX',
                        'icon': '🍎',
                        'port': ':8080 (Metal)',
                        'href': f'http://{dynamic_host}:8080/',
                        'target': '_blank',
                        'control': True,
                        'control_note': 'Apple Silicon',
                    },
                    {
                        'id': 'ollama',
                        'name': 'Ollama',
                        'icon': '🦙',
                        'port': ':11434',
                        'href': '/ollama/',
                        'target': '_blank',
                        'control': True,
                        'control_note': 'Local LLM',
                    },
                    {
                        'id': 'openrouter',
                        'name': 'OpenRouter',
                        'icon': '🌐',
                        'port': 'Free Models',
                        'clickable': False,
                        'status': 'info',
                    },
                ],
            },
            {
                'title': '💾 Storage & Monitoring',
                'services': [
                    {
                        'id': 'postgres',
                        'name': 'PostgreSQL',
                        'icon': '🐘',
                        'port': ':5432',
                        'clickable': False,
                    },
                    {
                        'id': 'grafana',
                        'name': 'Grafana',
                        'icon': '📈',
                        'port': ':3001',
                        'href': '/grafana/',
                        'target': '_blank',
                        'control': True,
                        'control_note': 'Dashboards',
                    },
                    {
                        'id': 'prometheus',
                        'name': 'Prometheus',
                        'icon': '📊',
                        'port': ':9090',
                        'href': '/prometheus/',
                        'target': '_blank',
                        'control': True,
                        'control_note': 'Metrics',
                    },
                    {
                        'id': 'pgadmin',
                        'name': 'PgAdmin',
                        'icon': '🔧',
                        'port': ':5050',
                        'href': '/pgadmin/',
                        'target': '_blank',
                    },
                ],
            },
        ]

        control_services = []
        for layer in service_layers:
            for service in layer['services']:
                if service.get('control'):
                    control_services.append(service)

        return render_template(
            'services.html',
            service_layers=service_layers,
            control_services=control_services,
        )
    
    @app.route('/litellm')
    def litellm():
        # Merged into /models — redirect for bookmarks
        from flask import redirect
        return redirect('/models', code=301)

    @app.route('/models')
    def models():
        return render_template('models.html')

    @app.route('/models/manager')
    @app.route('/model-manager')
    def models_manager():
        return render_template('models_manager.html')

    @app.route('/agents/manager')
    @app.route('/agent-manager')
    def agent_manager():
        return render_template('agent_manager.html')

    @app.route('/wallets')
    def wallets():
        from flask import redirect
        return redirect('/models', code=301)

    @app.route('/sprint-board')
    @app.route('/goals')
    def sprint_board():
        return render_template('sprint_board.html')

    @app.route('/heartbeat')
    def heartbeat():
        return render_template('heartbeat.html')

    @app.route('/knowledge')
    def knowledge():
        return render_template('knowledge.html')

    @app.route('/skill-graph')
    def skill_graph():
        return render_template('skill_graph.html')

    @app.route('/social')
    def social():
        return render_template('social.html')

    @app.route('/performance')
    def performance():
        return render_template('performance.html')

    @app.route('/security')
    def security():
        return render_template('security.html')

    # ============================================
    # Aria Operations Routes
    # ============================================
    @app.route('/sessions')
    def sessions():
        return render_template('sessions.html')

    @app.route('/working-memory')
    def working_memory():
        return render_template('working_memory.html')

    @app.route('/skills')
    def skills():
        # Merged into /skill-health
        return redirect('/skill-health', code=301)

    @app.route('/proposals')
    def proposals():
        return render_template('proposals.html')

    @app.route('/skill-stats')
    def skill_stats():
        return render_template('skill_stats.html')

    @app.route('/skill-health')
    def skill_health():
        return render_template('skill_health.html')

    @app.route('/soul')
    def soul():
        return render_template('soul.html')

    @app.route('/model-usage')
    def model_usage():
        return render_template('model_usage.html')

    @app.route('/cron')
    @app.route('/cron/')
    def cron_page():
        """Cron — redirect to unified operations cron page (S-13)."""
        return redirect('/operations/cron/', code=301)

    @app.route('/agents')
    @app.route('/agents/')
    def agents_page():
        """Agent management page."""
        return render_template('engine_agents.html')

    @app.route('/swarm-recap')
    @app.route('/swarm-recap/')
    @app.route('/swarm-recap/<session_id>')
    def swarm_recap(session_id=None):
        """Swarm decision recap page (S-09)."""
        return render_template('engine_swarm_recap.html', session_id=session_id)

    @app.route('/agent-dashboard')
    @app.route('/agent-dashboard/')
    def agent_dashboard_page():
        """Removed — redirect to /agents."""
        return redirect('/agents', code=301)

    @app.route('/rate-limits')
    def rate_limits():
        """Redirect to Model Manager (rate limits consolidated in S-04)."""
        return redirect('/model-manager', code=301)

    @app.route('/api-key-rotations')
    def api_key_rotations():
        # Removed — redirect to security
        return redirect('/security', code=301)

    # ============================================
    # Operations Hub Routes (Sprint 7)
    # ============================================
    @app.route('/operations')
    @app.route('/operations/')
    def operations():
        return render_template('operations.html')

    @app.route('/operations/cron/')
    def operations_cron():
        return render_template('engine_operations.html')

    @app.route('/operations/agents/')
    def operations_agents():
        return render_template('engine_agents_mgmt.html')

    @app.route('/operations/agents/<agent_id>/prompt')
    def operations_agent_prompt(agent_id):
        return render_template('engine_prompt_editor.html', agent_id=agent_id)

    @app.route('/operations/health/')
    def operations_health():
        return render_template('engine_health.html')

    @app.route('/operations/focus/')
    @app.route('/operations/focus')
    def operations_focus():
        """Focus profile management UI (E7-S76)."""
        return render_template('engine_focus.html')

    # ============================================
    # Engine Routes (native chat UI)
    # ============================================
    @app.route('/roundtable')
    @app.route('/roundtable/')
    @app.route('/roundtable/<session_id>')
    def roundtable(session_id=None):
        """Roundtable — multi-agent discussion visualization."""
        return render_template('engine_roundtable.html', session_id=session_id)

    @app.route('/chat/')
    @app.route('/chat/<session_id>')
    def chat(session_id=None):
        user_display_name = os.environ.get('USER_DISPLAY_NAME', 'User')
        return render_template(
            'engine_chat.html',
            session_id=session_id,
            user_display_name=user_display_name,
        )

    @app.route('/rpg')
    @app.route('/rpg/')
    def rpg():
        return render_template('rpg.html')

    @app.route('/memory-explorer')
    @app.route('/memory-explorer/')
    def memory_explorer():
        """Semantic memory explorer — browse pgvector embeddings, search, seed."""
        return render_template('memory_explorer.html')

    # Flask remains UI-only. All data access goes through the FastAPI service.

    return app


if __name__ == '__main__':
    app = create_app()
    app.run(host='0.0.0.0', port=int(os.environ.get('WEB_INTERNAL_PORT', '5000')), debug=True)
