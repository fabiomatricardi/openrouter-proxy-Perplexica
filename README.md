# OpenRouter Proxy with Vane Integration

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-green.svg)](https://fastapi.tiangolo.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

A lightweight proxy server for the OpenRouter API with **automatic API key rotation** and **Vane (formerly Perplexica) integration**. Bypass rate limits by rotating multiple API keys and access free OpenRouter models seamlessly.

> ### openrouter-proxy-Perplexica
> A simple proxy server for OpenRouter API. Meant initially for Perplexica/vane. Works with normal and free models, can rotate through multiple API keys in a round-robin fashion. 

## ✨ Features

### Core Features
- 🔑 **API Key Rotation** - Automatically rotate multiple OpenRouter API keys to bypass rate limits
- ⏱️ **Smart Cooldown** - Temporarily disable keys that hit rate limits, re-enable after cooldown
- 🔄 **Round-Robin & Random** - Choose key selection strategy (round-robin or random)
- 📊 **Streaming Support** - Full SSE (Server-Sent Events) passthrough for real-time responses
- 🛡️ **Access Control** - Local authentication with configurable access key
- 🌐 **Proxy Support** - Optional outbound proxy configuration

### Vane Integration (NEW!)
- 🎯 **Model Substitution** - Use `model: "openrouter"` in Vane, proxy substitutes with free models
- 🔐 **Special Authentication** - Bypass standard auth with `Bearer openrouter` token
- 🎲 **Free Model Rotation** - Round-robin through 3+ configurable free OpenRouter models
- ⚠️ **Auto-Fallback** - If a model is unavailable, automatically try the next in list
- 📝 **Pass-Through Mode** - Preserve all request parameters (stream, temperature, etc.)

## 🚀 Quick Start

### Prerequisites
- Python 3.10 or higher
- OpenRouter API keys (get free keys at https://openrouter.ai/keys)
- (Optional) Vane instance for AI search interface

### Installation

```bash
# Clone the repository
git clone https://github.com/fabiomatricardi/openrouter-proxy-Perplexica.git
cd openrouter-proxy-Perplexica

# Create virtual environment
python -m venv venv

# Activate virtual environment
# Windows:
venv\Scripts\activate
# Linux/Mac:
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### Configuration

1. **Copy the example config:**
   ```bash
   cp config.yml.example config.yml
   ```

2. **Edit `config.yml` with your settings:**
   ```yaml
   # Server settings
   server:
     host: "0.0.0.0"
     port: 5555
     access_key: "your_secure_access_key_here"
     log_level: "INFO"
     http_log_level: "INFO"

   # OpenRouter API keys (add multiple for rotation)
   openrouter:
     keys:
       - "sk-or-v1-your-first-key-here"
       - "sk-or-v1-your-second-key-here"
       - "sk-or-v1-your-third-key-here"
     key_selection_strategy: "round-robin"  # or "random"
     base_url: "https://openrouter.ai/api/v1"
     rate_limit_cooldown: 14400  # seconds (4 hours)
     free_only: false
     global_rate_delay: 0
     public_endpoints:
       - "/api/v1/models"

   # Vane integration settings
   vane:
     local_model_name: "openrouter"
     local_bearer_token: "openrouter"
     free_models:
       - "google/gemma-3-1b-it:free"
       - "meta-llama/llama-3.2-1b-instruct:free"
       - "qwen/qwen-2.5-7b-instruct:free"
     model_selection: "round-robin"  # or "random"
     enable_streaming: true

   # Optional: Outbound proxy
   requestProxy:
     enabled: false
     url: "socks5://username:password@example.com:1080"
   ```

### Run the Proxy

```bash
python main.py
```

You should see:
```
WARNING - Starting OpenRouter Proxy on 0.0.0.0:5555
WARNING - API URL: http://192.168.1.100:5555/api/v1
INFO - Health check: http://192.168.1.100:5555/health
```

---

## 🔌 Integration with Vane

### Step 1: Configure Vane Provider

In Vane's settings, add a new custom provider:

| Setting | Value |
|---------|-------|
| **API Endpoint** | `http://host.docker.internal:5555/api/v1` (or your server IP) |
| **Model Name** | `openrouter` (must match `vane.local_model_name`) |
| **API Key** | `openrouter` (must match `vane.local_bearer_token`) |

#### Add a new chat model named `openrouter` with API key `openrouter`

### Step 2: How It Works

```mermaid
graph LR
    A[Vane] -->|model: openrouter<br/>Bearer: openrouter| B[openrouter-proxy]
    B -->|Select free model<br/>round-robin| C[OpenRouter API]
    C -->|Real API key<br/>from rotation| D[Free Model]
    D -->|Stream chunks| B
    B -->|SSE passthrough| A
```

1. Vane sends request with `model: "openrouter"` + `Authorization: Bearer openrouter`
2. Proxy detects Vane request and bypasses standard authentication
3. Proxy selects next free model from your configured list (round-robin)
4. Request forwarded to OpenRouter with real API key from rotation pool
5. Response (including streaming) passed through unchanged to Vane

### Step 3: Test the Integration

```bash
# Test with curl (simulates Vane request)
curl -X POST http://localhost:5555/api/v1/chat/completions \
  -H "Authorization: Bearer openrouter" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "openrouter",
    "messages": [{"role": "user", "content": "Hello!"}],
    "stream": true
  }'
```

---

## 📡 API Endpoints

| Endpoint | Method | Auth Required | Description |
|----------|--------|---------------|-------------|
| `/api/v1{path:path}` | GET, POST | Yes* | Proxy all OpenRouter API calls |
| `/health` | GET | No | Health check endpoint |
| `/api/v1/models` | GET | No | List available models (public) |

\* Vane requests with `Bearer openrouter` bypass standard auth

---

## 🔧 Advanced Configuration

### Free Model Selection

OpenRouter's free models change frequently. Update `vane.free_models` in `config.yml`:

```yaml
vane:
  free_models:
    - "mistralai/mistral-7b-instruct:free"
    - "openchat/openchat-7b:free"
    - "huggingfaceh4/zephyr-7b-beta:free"
```

Check current free models at: https://openrouter.ai/models?max_price=0

### Key Rotation Strategies

| Strategy | Description | Best For |
|----------|-------------|----------|
| `round-robin` | Cycle through keys sequentially | Even distribution |
| `random` | Pick random key each request | Load balancing |

### Rate Limit Handling

When a key hits rate limit:
1. Key is temporarily disabled
2. Next key in rotation is used
3. Disabled key re-enabled after `rate_limit_cooldown` seconds (default: 4 hours)
4. If **all keys** are disabled, terminal alert is shown

---

## 🐛 Troubleshooting

### Common Issues

| Issue | Solution |
|-------|----------|
| **"Invalid access key"** | Verify Vane uses `Bearer openrouter` (case-sensitive) |
| **No response from Vane** | Check proxy is running on `0.0.0.0:5555`, not `127.0.0.1` |
| **Model not found errors** | Update `vane.free_models` with currently available free models |
| **All keys disabled** | Wait for cooldown or add more API keys to `config.yml` |
| **Streaming not working** | Ensure `vane.enable_streaming: true` and Vane supports SSE |
| **Json.loads error** | Already fixed in latest version - update your files |

### Enable Debug Logging

```yaml
server:
  log_level: "DEBUG"
  http_log_level: "DEBUG"
```

### Check Proxy Logs

```bash
# Watch logs in real-time
tail -f logs/openrouter-proxy.log  # If logging to file
# Or check terminal output for errors
```

---

## 🧪 Testing

### Test Non-Streaming Request
```bash
python test_myProxy.py
```


---

## 📁 Project Structure

```
openrouter-proxy/
├── main.py                 # Entry point
├── routes.py               # API routes & proxy logic
├── config.py               # Configuration loading & validation
├── utils.py                # Utility functions
├── key_manager.py          # API key rotation logic
├── model_selector.py       # Vane model selection (round-robin)
├── constants.py            # Constants & error codes
├── config.yml.example      # Example configuration
├── requirements.txt        # Python dependencies
├── test_myProxy.py         # Python file for local test
└── README.md               # This file
```

---

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

---

## 🙏 Acknowledgments

- Original project by [Aculeasis/openrouter-proxy](https://github.com/Aculeasis/openrouter-proxy)
- Vane (formerly Perplexica) by [ItzCrazyKns/Vane](https://github.com/ItzCrazyKns/Vane)
- OpenRouter API for providing free model access

---

## 📬 Support

- **Issues**: Open an issue on GitHub for bugs or feature requests
- **Discussions**: Use GitHub Discussions for questions and community support

---

**Enjoy unlimited access to free OpenRouter models with Vane! 🚀**
```

---


