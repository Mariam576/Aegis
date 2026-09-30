# Aegis (AI Research Agent)

Type a topic into the website. The agent then:

1. plans the research
2. searches the web
3. reads each page
4. extracts claims, and checks every supporting quote against the real page text
5. compares sources to find where they agree and disagree
6. writes a report
7. turns the report's source markers into numbered citations with a reference list

Each stage shows up live in the browser as it happens, using Server-Sent Events.

**Runs completely free:** Google Gemini (free tier) for the AI, and Tavily (free tier) or DuckDuckGo (no key) for search.

---

## Setup (Python 3.10+)

**1. Get your free API keys**

- **Gemini API key** (required, free): sign in to **Google AI Studio** (aistudio.google.com) with your Google account and click **Get API key**. No credit card is needed.
- **Tavily API key** (optional, free 1,000 credits/month at tavily.com). If you leave it empty, the agent uses DuckDuckGo.

**2. Install and run**

```bash
# Clone the repository
git clone https://github.com/Mariam576/aegis.git
cd aegis

# Create a virtual environment
python -m venv .venv

# Windows
.venv\Scripts\activate
copy .env.example .env

# macOS / Linux
source .venv/bin/activate
cp .env.example .env

# Install dependencies
pip install -r requirements.txt

# now open .env and paste your GEMINI_API_KEY (and TAVILY_API_KEY if you have one)

# Start the server
cd backend
uvicorn main:app --reload
```

**3. Open http://localhost:8000**

## Free-tier notes

- **Rate limits:** the free tier limits requests per minute and per day, and each model has its own limits. You can see your exact numbers in AI Studio. One run makes about **8 Gemini requests on Quick, 11 on Standard, and 15 on Deep**.
- **Pacing:** the code spaces requests out (`GEMINI_RPM`) and automatically retries when Google says "too many requests". This is why a run takes a minute or two. If you still get rate-limit errors, lower `GEMINI_RPM` in `.env`.
- **Two models:** the agent uses a "smart" model for planning and writing and a "fast" model for reading sources. Because limits are counted per model, this spreads the load.
- **Privacy:** Google uses free-tier prompts to improve its products, so don't research private or confidential material.
- **Model names:** if Google renames or retires a model, pick a current one from the model list in AI Studio and update `MODEL_SMART` / `MODEL_FAST` in `.env`.

## Deploying

This runs on Render, Railway, Fly.io or any VPS. Set the same environment variables there and use this start command:

```bash
cd backend && uvicorn main:app --host 0.0.0.0 --port $PORT
```

On a public site, everyone shares your free-tier quota, so add rate limiting per user before sharing it widely.