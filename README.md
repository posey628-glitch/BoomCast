# BoomCast

An independent Streamlit rebuild of the LaunchCast power-hitting dashboard.

## Run locally

```bash
python3 -m pip install -r requirements.txt
streamlit run app.py
```

The app opens with a demo slate. Use **Live MLB** in the sidebar for the current
schedule, confirmed lineups when posted, and live season Statcast inputs. You
can also upload a CSV to analyze your own data. `player_name` and `team` are
required; all modeling columns are optional and documented in the app's
**Import guide**.

## Design choices

- No hidden remote fetches or silent all-empty fallbacks.
- Scores are normalized within the current slate and use only fields that are
  actually available for a player.
- The Custom model tab exposes all scoring weights so rankings are auditable.
- Live data failures return a visible message and preserve a usable demo slate;
  they never masquerade as an empty, successful slate.

## Hosting

The repository includes a Docker configuration tested against Python 3.11:

```bash
docker build -t launchcast .
docker run --rm -p 8501:8501 -v launchcast-data:/data \
  -e LAUNCHCAST_DATA_DIR=/data launchcast
```

The optional GitHub Actions keep-awake workflow needs an `APP_URL` repository
secret. It only pings a hosted app; it does not save or grade snapshots.
Snapshots default to `work/`; use `LAUNCHCAST_DATA_DIR` with a persistent volume
before relying on the Learning tab in a container deployment.
