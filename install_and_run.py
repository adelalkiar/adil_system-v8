"""
Auto-installer and launcher for Al-Adil System v7
Works on Windows, Mac, Linux
"""
import sys, subprocess, os, time, webbrowser, platform

def install(pkg):
    subprocess.check_call(
        [sys.executable, "-m", "pip", "install", pkg, "--quiet", "--no-warn-script-location"])

# تغيير المجلد لمجلد السكريبت
os.chdir(os.path.dirname(os.path.abspath(__file__)))

packages = [
    "fastapi", "uvicorn", "pandas", "openpyxl", "xlrd",
    "cryptography", "python-multipart", "aiofiles", "pyodbc"
]

print("\n" + "="*50)
print("  Al-Adil System v7 - Auto Setup")
print("="*50)
print("  Python:", sys.version.split()[0])
print("  OS:", platform.system())
print()

print("[1/3] Checking packages...")
for pkg in packages:
    mod = pkg.replace("-","_")
    try:
        __import__(mod)
        print("  OK:", pkg)
    except ImportError:
        print("  Installing:", pkg, "...", end=" ", flush=True)
        try:
            install(pkg)
            print("done")
        except Exception as e:
            print("FAILED:", e)

# فحص ODBC Driver
print()
print("[2/3] Checking ODBC Driver...")
try:
    import pyodbc
    sql_drivers = [d for d in pyodbc.drivers() if "SQL Server" in d]
    if sql_drivers:
        print("  OK - Found:", sql_drivers[0])
    else:
        print("  WARNING: No SQL Server ODBC Driver found!")
        print("  Download from: https://aka.ms/downloadmsodbcsql")
        print("  (ODBC Driver 17 or 18 for SQL Server)")
except Exception as e:
    print("  Could not check drivers:", e)

print()
print("[3/3] Starting server...")
print("  URL:   http://localhost:8765")
print("  Admin: http://localhost:8765/admin")
print()

import threading
def open_browser():
    time.sleep(2)
    webbrowser.open("http://localhost:8765")

threading.Thread(target=open_browser, daemon=True).start()
subprocess.run([sys.executable, "app.py"])
