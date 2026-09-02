# Tailored Troubleshooting Guide

Having trouble running Tailored? This guide covers common issues and their solutions.

## Quick Recovery Steps

### 1. Virtual Environment Corruption
If you see errors like `ModuleNotFoundError` or the app won't start:

**Windows:**
```
Tailored.bat --clean
```

**macOS/Linux:**
```
bash start_tailored.sh --clean
```

This removes the old virtual environment and rebuilds it from scratch. Takes a few minutes on first run.

---

## Common Issues

### Error: "ModuleNotFoundError: No module named 'pydantic_core'"
This usually means the virtual environment got corrupted or pip failed during install.

**Fix:**
1. Run `Tailored.bat --clean` (Windows) or `bash start_tailored.sh --clean` (macOS/Linux)
2. Wait for it to rebuild the environment

---

### Error: "Python 3.11+ could not be found"
The launcher can't locate a compatible Python installation.

**Fix:**
1. Install Python 3.11+ from [python.org](https://www.python.org/downloads/)
2. **Windows:** On the first install screen, **CHECK "Add python.exe to PATH"**
3. Restart your computer (so Windows picks up the PATH change)
4. Run `Tailored.bat` again

**Verify installation:**
```
python --version
```
(Should show 3.11 or higher)

---

### Error: "Failed to create the Python virtual environment"
Usually a permissions or disk space issue.

**Fix:**
1. Run as Administrator (right-click → "Run as administrator")
2. Make sure you have at least 1 GB free disk space
3. Check that the project folder isn't read-only

**Advanced:** Try manually creating the venv:
```
python -m venv .venv
```

---

### Error: "Failed to install dependencies" / pip errors
Dependencies installation failed, often due to network or pip version issues.

**Fix:**
1. Try again with `Tailored.bat --clean` (Windows) or `bash start_tailored.sh --clean` (macOS/Linux)
2. If that doesn't work, manually upgrade pip:

**Windows:**
```
.venv\Scripts\python -m pip install --upgrade pip
.venv\Scripts\python -m pip install -r requirements.txt
```

**macOS/Linux:**
```
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
```

---

### Error: "Chromium install failed" / PDF export doesn't work
Playwright/Chromium didn't install, but this doesn't block the app—just PDF export.

**Fix (optional):** Manually install Chromium:

**Windows:**
```
.venv\Scripts\python -m playwright install chromium
```

**macOS/Linux:**
```
.venv/bin/python -m playwright install chromium
```

---

### Error: "Permission denied" or "Access denied" errors
File permissions issue, usually on Windows.

**Fix:**
1. Run as Administrator (right-click `Tailored.bat` → "Run as administrator")
2. Or run from PowerShell with elevated permissions:
   ```
   Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
   Tailored.bat
   ```

---

### Error: "No Anthropic API key found" / "Demo mode"
The app launches but can't call the AI API.

**Fix:**
1. Get a free API key from [console.anthropic.com](https://console.anthropic.com/)
2. The launcher will ask you to paste it into `.env` (opens in Notepad)
3. Save and try again
4. Or choose option [2] to use **demo mode** (no key needed, sample data)

---

### Error: Port 8547 already in use
Another app is using the same port.

**Fix:**
Either:
1. Stop the other app
2. Or manually run on a different port:

**Windows:**
```
set TAILORED_PORT=8548
.venv\Scripts\python run.py
```

**macOS/Linux:**
```
export TAILORED_PORT=8548
.venv/bin/python run.py
```

Then open `http://127.0.0.1:8548` in your browser.

---

### Error: "Connection refused" / Can't connect to the app
The server crashed or didn't start.

**Fix:**
1. Check the error message in the terminal where you ran `Tailored.bat` or `start_tailored.sh`
2. Try the quick recovery steps above
3. If still failing, run in the terminal to see full error details:

**Windows:**
```
.venv\Scripts\python run.py
```

**macOS/Linux:**
```
.venv/bin/python run.py
```

---

## Manual Start (without the launcher)

If the launcher script isn't working, you can start the app manually:

**Windows:**
```
.venv\Scripts\Activate.ps1
python run.py
```

**macOS/Linux:**
```
source .venv/bin/activate
python run.py
```

The app opens on `http://127.0.0.1:8547`.

---

## The Nuclear Option: Complete Reset

If nothing else works, start completely fresh:

**Windows (PowerShell):**
```powershell
Remove-Item .venv -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item data -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item .env -ErrorAction SilentlyContinue
Remove-Item frontend\dist -Recurse -Force -ErrorAction SilentlyContinue
Tailored.bat
```

**macOS/Linux (Terminal):**
```bash
rm -rf .venv data .env frontend/dist
bash start_tailored.sh
```

This wipes everything and starts fresh. Your profiles and saved jobs (in `data/tailored.db`) are deleted, so only do this if you're sure.

---

## Environment Variables (Advanced)

You can customize behavior with environment variables before running:

- `ANTHROPIC_API_KEY=sk-ant-...` — Your API key (or set in `.env`)
- `TAILORED_FAKE=1` — Run in demo mode (no API key needed)
- `TAILORED_DATA_DIR=<path>` — Change where data is stored (default: `./data`)
- `TAILORED_HOST=<host>` — Change the server host (default: `127.0.0.1`)
- `TAILORED_PORT=<port>` — Change the server port (default: `8547`)

**Example (Windows):**
```
set TAILORED_FAKE=1
set TAILORED_PORT=9999
.venv\Scripts\python run.py
```

**Example (macOS/Linux):**
```
export TAILORED_FAKE=1
export TAILORED_PORT=9999
.venv/bin/python run.py
```

---

## Getting Help

1. **Check the error message** — Run manually (`python run.py`) to see full details
2. **Try the recovery steps** — `Tailored.bat --clean` or `bash start_tailored.sh --clean`
3. **Review logs** — If there's a `data/` folder, check for `.db` or log files
4. **Restart your computer** — Fixes PATH and permission issues
5. **Run as Administrator** — (Windows) Right-click and "Run as administrator"

---

## Still Stuck?

If you've tried everything above and it still isn't working:

1. Make note of the exact error message
2. Check that Python 3.11+ is installed: `python --version`
3. Try running the manual setup from the README:
   ```
   python -m venv .venv
   .venv\Scripts\activate    # or: source .venv/bin/activate
   pip install -r requirements.txt
   python run.py
   ```

Good luck.
