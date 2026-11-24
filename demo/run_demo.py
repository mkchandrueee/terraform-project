"""One command to start the client demo:   python demo/run_demo.py [--big]

Builds the demo data if missing, points DataRecon at an isolated demo profile (your real saved
connections/passwords are NOT loaded), and starts the app.
"""
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent


def main():
    if not (HERE / ".demo_profile.json").exists() or not (HERE / "data" / "legacy.db").exists() \
            or ("--big" in sys.argv and not (HERE / "data" / "big_legacy.csv").exists()):
        subprocess.check_call([sys.executable, str(HERE / "make_demo_data.py"), *[a for a in sys.argv[1:] if a == "--big"]])
    env = dict(os.environ, DATARECON_PROFILE=str(HERE / ".demo_profile.json"), DATARECON_KEY=str(HERE / ".demo.key"))
    if not (ROOT / "frontend" / "dist" / "index.html").exists():
        raise SystemExit("Build the frontend first: npm --prefix frontend ci && npm --prefix frontend run build")
    print("Open the Equaliser demo at http://127.0.0.1:8000 (Ctrl+C to stop)")
    subprocess.check_call([sys.executable, "-m", "uvicorn", "datarecon_api:app",
                           "--host", "127.0.0.1", "--port", "8000"], env=env, cwd=ROOT)


if __name__ == "__main__":
    main()
