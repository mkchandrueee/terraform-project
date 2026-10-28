"""One command to start the client demo:   python demo/run_demo.py [--big]

Builds the demo data if missing, points DataRecon at an isolated demo profile (your real saved
connections/passwords are NOT loaded), and opens the app.
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
    print("Starting DataRecon demo - browser opens at http://localhost:8501 (Ctrl+C to stop)")
    subprocess.call([sys.executable, "-m", "streamlit", "run", str(ROOT / "datarecon.py"),
                     "--browser.gatherUsageStats", "false"], env=env, cwd=ROOT)


if __name__ == "__main__":
    main()
