# MLX Local Model Setup Guide — Apple Silicon Mac

> **TICKET-19** — Local Model Optimization
> This guide covers setting up `mlx-lm` to serve quantised models locally for the Aria stack.

---

## Prerequisites

| Requirement | Minimum |
|---|---|
| macOS | 13.0 Ventura or later |
| Chip | Apple Silicon (M1/M2/M3/M4) |
| Python | 3.11+ |
| RAM | 16 GB (4B model) / 24 GB+ (8B model with Docker) |
| Homebrew | Latest |

Verify your chip:

```bash
sysctl -n machdep.cpu.brand_string   # Should show "Apple M…"
python3 --version                     # 3.11+
```

---

## 1. Install mlx-lm

```bash
# Create or activate a dedicated venv (recommended)
python3 -m venv ~/.venvs/mlx-server
source ~/.venvs/mlx-server/bin/activate

pip install --upgrade pip
pip install mlx-lm
```

---

## 2. Download / Convert a Model

### Option A — Use a pre-quantised Hub model (fastest)

```bash
# Qwen3 4B Instruct — 4-bit, ~2.1 GB RAM
mlx_lm.generate \
  --model mlx-community/Qwen3-4B-Instruct-2507-4bit \
  --prompt "Hello, who are you?" \
  --max-tokens 64
```

The model is automatically cached under `~/.cache/huggingface/hub/`.

### Option B — Convert & quantise yourself

```bash
# Download the full-precision model
mlx_lm.convert \
  --hf-path Qwen/Qwen3-4B-Instruct \
  --mlx-path ~/models/qwen3-4b-4bit \
  -q --q-bits 4

# Test generation
mlx_lm.generate \
  --model ~/models/qwen3-4b-4bit \
  --prompt "Hello" \
  --max-tokens 64
```

---

## 3. Start the Server

```bash
mlx_lm.server \
  --model mlx-community/Qwen3-4B-Instruct-2507-4bit \
  --port 8080
```

Verify it is running:

```bash
curl http://localhost:8080/v1/models
```

Expected response: a JSON object listing the loaded model.

### Server flags

| Flag | Description |
|---|---|
| `--model PATH_OR_HF_ID` | Model to load |
| `--port 8080` | Listening port |
| `--host 0.0.0.0` | Bind address (default `127.0.0.1`) |
| `--trust-remote-code` | Needed for some model architectures |

### Test Command

```bash
curl http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "mlx-community/Qwen3-4B-Instruct-2507-4bit",
    "messages": [{"role": "user", "content": "Hello"}],
    "max_tokens": 100
  }'
```

---

## 4. Auto-Start with launchd

Create a LaunchAgent plist so the server starts on login.

```bash
mkdir -p ~/Library/LaunchAgents
cat > ~/Library/LaunchAgents/com.aria.mlx-server.plist << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.aria.mlx-server</string>

    <key>ProgramArguments</key>
    <array>
        <!-- Full path to the Python in your venv -->
        <string>/Users/YOUR_USER/.venvs/mlx-server/bin/python3</string>
        <string>-m</string>
        <string>mlx_lm.server</string>
        <string>--model</string>
        <string>mlx-community/Qwen3-4B-Instruct-2507-4bit</string>
        <string>--port</string>
        <string>8080</string>
    </array>

    <key>RunAtLoad</key>
    <true/>

    <key>KeepAlive</key>
    <true/>

    <key>StandardOutPath</key>
    <string>/tmp/mlx-server.stdout.log</string>

    <key>StandardErrorPath</key>
    <string>/tmp/mlx-server.stderr.log</string>

    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/usr/local/bin:/usr/bin:/bin</string>
    </dict>
</dict>
</plist>
EOF
```

> **Important:** Replace `YOUR_USER` with your macOS username.

Load / manage the service:

```bash
# Load (start now + on login)
launchctl load ~/Library/LaunchAgents/com.aria.mlx-server.plist

# Check status
launchctl list | grep mlx

# View logs
tail -f /tmp/mlx-server.stderr.log

# Restart
launchctl stop com.aria.mlx-server
launchctl start com.aria.mlx-server

# Unload (disable)
launchctl unload ~/Library/LaunchAgents/com.aria.mlx-server.plist
```

---

## 5. RAM Requirements

| Model Size | VRAM / Unified Memory | Notes |
|---|---|---|
| **4B (4-bit)** | **~2.1 GB** | Runs on 8 GB Macs; recommended default |
| **8B (4-bit)** | **~5 GB** | Needs 24 GB+ total when Docker stack is running |
| **14B (4-bit)** | **~8 GB** | M2 Pro / M3 Pro 36 GB+ recommended |
| **32B (4-bit)** | **~18 GB** | M3 Max 64 GB+ only |

The Aria Docker stack (LiteLLM + Supabase + Aria Engine) typically uses 4-8 GB.
Plan total = Docker overhead + model size + 2 GB system headroom.

---

## 6. Model Switching Procedure

1. **Stop** the current server (or let launchd restart it):

   ```bash
   launchctl unload ~/Library/LaunchAgents/com.aria.mlx-server.plist
   ```

2. **Edit** the plist to point to the new model path/ID.

3. **Update** `aria_models/models.yaml`:
  - Change `models.qwen3.5_mlx.litellm.model` to the new HuggingFace ID.
   - Change the `_note` field to document the switch.

4. **Reload** the service:

   ```bash
   launchctl load ~/Library/LaunchAgents/com.aria.mlx-server.plist
   ```

5. **Verify**:

   ```bash
   curl http://localhost:8080/v1/models
  python tests/load/benchmark_models.py --models qwen3.5_mlx
   ```

---

## 7. LiteLLM Integration

In `litellm-config.yaml` (auto-generated from `models.yaml`):

```yaml
- model_name: qwen3.5_mlx
  litellm_params:
    model: openai/mlx-community/Qwen3-4B-Instruct-2507-4bit
    api_base: http://host.docker.internal:8080/v1
    api_key: not-needed
```

---

## 8. Disabling Ollama (Legacy)

> **Note:** As of v3.0.0, Ollama is no longer part of the standard stack. LiteLLM handles all model routing. This section is retained only for legacy reference.

If Ollama was previously installed, disable it to free up RAM:

```bash
# Stop Ollama
pkill -f ollama
killall Ollama

# Disable autostart
launchctl unload ~/Library/LaunchAgents/com.ollama.ollama.plist
```

All model routing is now handled by LiteLLM. Local models run via MLX and are accessed through LiteLLM's proxy configuration.

---

## 9. Troubleshooting

### Server won't start

```
RuntimeError: Failed to load model
```

- Ensure the model ID is correct and you have internet for the first download.
- Check disk space: `df -h ~`.
- Try `--trust-remote-code` flag.

### Out of memory

```
zsh: killed     mlx_lm.server ...
```

- Switch to a smaller model (4B instead of 8B).
- Close other heavy apps (Docker, browsers).
- Check memory pressure: `memory_pressure` or Activity Monitor.

### Connection refused from Docker

The Aria stack connects to `http://host.docker.internal:8080`.
This requires Docker Desktop ≥ 4.1. Verify:

```bash
# From inside a container:
curl http://host.docker.internal:8080/v1/models
```

If it fails, check that `host.docker.internal` resolves:

```bash
docker run --rm alpine ping -c1 host.docker.internal
```

### Slow first request

The very first inference after loading takes longer (kernel compilation).
Subsequent requests are fast. This is normal MLX behavior.

### Port conflict

If port 8080 is occupied:

```bash
lsof -i :8080
```

Change the port in both the plist and `models.yaml` → `qwen3.5_mlx.litellm.api_base`.

### Logs

```bash
tail -100 /tmp/mlx-server.stderr.log
tail -100 /tmp/mlx-server.stdout.log
```

## Performance Notes

- First request is slow (model loading into GPU memory)
- Subsequent requests are fast
- Memory stays allocated until server restart
- M4 Mac Mini can run 8B models comfortably
