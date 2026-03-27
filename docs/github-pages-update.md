# Updating GitHub Pages Deployment

## Quick Update (after Stage 2 finishes or new data)

```bash
cd ~/reddit_scrap

# 1. Export latest data as static JSON from local DB
#    (or from Frame Desktop DB — SCP it first)
/Users/freeman/miniconda3/envs/ai_edu_env/bin/python scripts/export_static.py

# 2. Commit and push — GitHub Action auto-deploys
git add frontend/public/data/
git commit -m "Update static data"
git push
```

The GitHub Action builds with `VITE_STATIC=true` and deploys to Pages automatically.

## Full Update (code + data)

```bash
cd ~/reddit_scrap

# 1. Export static JSON
/Users/freeman/miniconda3/envs/ai_edu_env/bin/python scripts/export_static.py

# 2. Stage all changes
git add frontend/ backend/ scripts/ docs/

# 3. Commit and push
git commit -m "Update dashboard"
git push
```

## Using Frame Desktop DB (latest data)

The Frame Desktop DB is ahead of local (Stage 2 runs there). To export from it:

```bash
# Option A: SCP the DB to local, then export
sshpass -p 'Zhiyuan#115' scp -o StrictHostKeyChecking=no \
  freeman@192.168.1.146:~/reddit_scrap/data/reddit_ai_k12.db \
  ~/reddit_scrap/data/reddit_ai_k12.db

/Users/freeman/miniconda3/envs/ai_edu_env/bin/python scripts/export_static.py

# Option B: Run export on Frame Desktop, SCP the JSON back
sshpass -p 'Zhiyuan#115' ssh freeman@192.168.1.146 \
  'cd ~/reddit_scrap && ~/reddit_scrap/.venv/bin/python3 scripts/export_static.py'

sshpass -p 'Zhiyuan#115' scp -o StrictHostKeyChecking=no -r \
  freeman@192.168.1.146:~/reddit_scrap/frontend/public/data/ \
  ~/reddit_scrap/frontend/public/data/
```

Then commit and push as above.

## Also Update Frame Desktop

After pushing to GitHub, also update the live Frame server:

```bash
# Build for API mode (no VITE_STATIC)
cd ~/reddit_scrap/frontend && npm run build

# Sync to Frame
sshpass -p 'Zhiyuan#115' scp -o StrictHostKeyChecking=no -r \
  dist freeman@192.168.1.146:~/reddit_scrap/frontend/

# Sync backend if changed
sshpass -p 'Zhiyuan#115' scp -o StrictHostKeyChecking=no \
  ../backend/main.py freeman@192.168.1.146:~/reddit_scrap/backend/

# Restart web server
sshpass -p 'Zhiyuan#115' ssh freeman@192.168.1.146 \
  'screen -X -S webgraph quit; sleep 1; screen -dmS webgraph bash -c "cd ~/reddit_scrap && ~/reddit_scrap/.venv/bin/uvicorn backend.main:app --host 0.0.0.0 --port 3000; exec bash"'
```

## URLs

| Deployment | URL | Data Source |
|---|---|---|
| **GitHub Pages** | https://freeman-gif.github.io/reddit-ai-k12-graph/ | Static JSON (snapshot) |


## How Static Mode Works

- `frontend/src/api.js` checks `VITE_STATIC` env var at build time
- When `true`: fetches from `/data/*.json` (pre-exported static files)
- When `false` (default): fetches from `/api/*` (live FastAPI backend)
- Year filtering in static mode is done client-side (filters the full JSON)
- Post detail in static mode loads from `/data/post_{id}.json`

## Repo

https://github.com/Freeman-gif/reddit-ai-k12-graph
