"""
محرك الترخيص - نظام العادل لتوزيع الأقساط
"""
import os, json, hashlib, sqlite3, platform, subprocess
from datetime import datetime, timedelta
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import base64, secrets, string

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH  = os.path.join(BASE_DIR, "database", "licenses.db")
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

MASTER_SECRET = "ADIL_SYSTEM_2024_MASTER_KEY_SECURE_@#$"

def _get_key_file() -> str:
    sys_name = platform.system()
    if sys_name == "Windows":
        base = os.environ.get("APPDATA", os.path.expanduser("~"))
    elif sys_name == "Darwin":
        base = os.path.expanduser("~/Library/Application Support")
    else:
        base = os.path.expanduser("~/.config")
    folder = os.path.join(base, "AdilSystem")
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, ".syskey")

def _get_fernet() -> Fernet:
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32,
                     salt=b"adil_salt_2024", iterations=100000)
    key = base64.urlsafe_b64encode(kdf.derive(MASTER_SECRET.encode()))
    return Fernet(key)

def get_hardware_id() -> str:
    parts = []
    try: parts.append(platform.node())
    except: pass
    try: parts.append(platform.machine())
    except: pass
    try:
        sys_name = platform.system()
        if sys_name == "Windows":
            r = subprocess.check_output("wmic csproduct get uuid", shell=True,
                stderr=subprocess.DEVNULL).decode(errors="ignore")
            lines = [l.strip() for l in r.strip().splitlines()
                     if l.strip() and l.strip().upper() != "UUID"]
            if lines: parts.append(lines[0])
        elif sys_name == "Linux":
            for p in ["/etc/machine-id", "/var/lib/dbus/machine-id"]:
                if os.path.exists(p):
                    with open(p) as f: parts.append(f.read().strip()); break
        elif sys_name == "Darwin":
            r = subprocess.check_output(["ioreg","-rd1","-c","IOPlatformExpertDevice"],
                stderr=subprocess.DEVNULL).decode(errors="ignore")
            for line in r.splitlines():
                if "IOPlatformUUID" in line:
                    parts.append(line.split("=")[-1].strip().strip('"'))
    except: pass
    raw = "|".join(p for p in parts if p) or platform.node() or "unknown"
    return hashlib.sha256(raw.encode()).hexdigest()[:32].upper()

def _get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = _get_conn()
    conn.execute("""CREATE TABLE IF NOT EXISTS licenses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        license_key TEXT UNIQUE NOT NULL,
        client_name TEXT,
        license_type TEXT NOT NULL,
        hardware_id TEXT,
        created_at TEXT,
        expires_at TEXT,
        is_active INTEGER DEFAULT 1,
        notes TEXT)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS activation_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        license_key TEXT, hardware_id TEXT, action TEXT, timestamp TEXT)""")
    conn.commit(); conn.close()

def generate_license_key(client_name, license_type, duration_days=None, notes=""):
    init_db()
    chars = string.ascii_uppercase + string.digits
    key = "ADIL-" + "-".join("".join(secrets.choice(chars) for _ in range(4)) for _ in range(4))
    now = datetime.now()
    expires = None
    if   license_type == "monthly": expires = (now + timedelta(days=30)).isoformat()
    elif license_type == "annual":  expires = (now + timedelta(days=365)).isoformat()
    elif duration_days: expires = (now + timedelta(days=int(duration_days))).isoformat()
    conn = _get_conn()
    conn.execute("INSERT INTO licenses (license_key,client_name,license_type,created_at,expires_at,is_active,notes) VALUES (?,?,?,?,?,1,?)",
                 (key, client_name, license_type, now.isoformat(), expires, notes))
    conn.commit(); conn.close()
    return key

def activate_license(key: str) -> dict:
    init_db()
    hw_id = get_hardware_id()
    conn  = _get_conn()
    row   = conn.execute("SELECT * FROM licenses WHERE license_key=?", (key,)).fetchone()
    if not row:
        conn.close()
        return {"success": False, "message": "مفتاح الترخيص غير صحيح أو غير موجود"}
    if not row["is_active"]:
        conn.close()
        return {"success": False, "message": "هذا الترخيص موقوف من قِبل المطور"}
    if row["expires_at"]:
        exp = datetime.fromisoformat(row["expires_at"])
        if datetime.now() > exp:
            conn.execute("UPDATE licenses SET is_active=0 WHERE license_key=?", (key,))
            conn.commit(); conn.close()
            return {"success": False, "message": f"انتهت صلاحية الترخيص بتاريخ {exp.strftime('%Y-%m-%d')}"}
    if row["hardware_id"] and row["hardware_id"] != hw_id:
        conn.close()
        return {"success": False, "message": "هذا الترخيص مرتبط بجهاز مختلف. تواصل مع المطور"}
    conn.execute("UPDATE licenses SET hardware_id=? WHERE license_key=?", (hw_id, key))
    conn.execute("INSERT INTO activation_log (license_key,hardware_id,action,timestamp) VALUES (?,?,?,?)",
                 (key, hw_id, "activate", datetime.now().isoformat()))
    conn.commit(); conn.close()
    if not _save_local_activation(key, dict(row)):
        return {"success": False, "message": "فشل حفظ ملف التفعيل - شغّل كمسؤول (Run as Administrator)"}
    return {"success": True, "message": "تم التفعيل بنجاح!", "type": row["license_type"], "expires": row["expires_at"]}

def _save_local_activation(key: str, data: dict) -> bool:
    try:
        payload = json.dumps({"key": key, "hw": get_hardware_id(),
                              "type": data["license_type"], "expires": data.get("expires_at"),
                              "ts": datetime.now().isoformat()})
        with open(_get_key_file(), "wb") as fp:
            fp.write(_get_fernet().encrypt(payload.encode()))
        return True
    except Exception as e:
        print(f"[ERROR] save: {e}"); return False

def verify_license() -> dict:
    init_db()
    key_file = _get_key_file()
    if not os.path.exists(key_file):
        return {"valid": False, "message": "لم يتم تفعيل البرنامج"}
    try:
        data = json.loads(_get_fernet().decrypt(open(key_file,"rb").read()).decode())
        if data.get("hw") != get_hardware_id():
            return {"valid": False, "message": "ملف التفعيل لا يتطابق مع هذا الجهاز"}
        conn = _get_conn()
        row  = conn.execute("SELECT is_active,expires_at,license_type,client_name FROM licenses WHERE license_key=?",
                            (data["key"],)).fetchone()
        conn.close()
        # جهاز العميل - DB غير موجودة - نثق بالملف المشفر
        if not row:
            days_left = None
            if data.get("expires"):
                delta = datetime.fromisoformat(data["expires"]) - datetime.now()
                if delta.days < 0:
                    return {"valid": False, "message": "انتهت صلاحية الترخيص"}
                days_left = delta.days
            return {"valid": True, "type": data.get("type","lifetime"),
                    "client": "—", "days_left": days_left,
                    "expires": data.get("expires"), "key": data["key"]}
        if not row["is_active"]:
            return {"valid": False, "message": "تم إيقاف ترخيصك. تواصل مع المطور"}
        days_left = None
        if row["expires_at"]:
            delta = datetime.fromisoformat(row["expires_at"]) - datetime.now()
            if delta.days < 0:
                return {"valid": False, "message": f"انتهت صلاحية الترخيص منذ {abs(delta.days)} يوم"}
            days_left = delta.days
        return {"valid": True, "type": row["license_type"], "client": row["client_name"],
                "days_left": days_left, "expires": row["expires_at"], "key": data["key"]}
    except Exception as e:
        return {"valid": False, "message": f"خطأ في التحقق: {str(e)}"}

def admin_list_licenses() -> list:
    init_db()
    conn = _get_conn()
    rows = conn.execute("SELECT license_key,client_name,license_type,created_at,expires_at,is_active,hardware_id,notes FROM licenses ORDER BY id DESC").fetchall()
    conn.close()
    result = []
    for r in rows:
        days_left = None
        if r["expires_at"]:
            days_left = (datetime.fromisoformat(r["expires_at"]) - datetime.now()).days
        result.append({"key": r["license_key"], "client": r["client_name"], "type": r["license_type"],
                       "created": r["created_at"][:10], "expires": r["expires_at"][:10] if r["expires_at"] else "دائم",
                       "active": bool(r["is_active"]), "bound": bool(r["hardware_id"]),
                       "days_left": days_left, "notes": r["notes"]})
    return result

def admin_toggle_license(key: str, active: bool):
    init_db()
    conn = _get_conn()
    conn.execute("UPDATE licenses SET is_active=? WHERE license_key=?", (1 if active else 0, key))
    conn.commit(); conn.close()

def admin_delete_license(key: str):
    init_db()
    conn = _get_conn()
    conn.execute("DELETE FROM licenses WHERE license_key=?", (key,))
    conn.commit(); conn.close()

def admin_extend_license(key: str, days: int):
    init_db()
    conn = _get_conn()
    row  = conn.execute("SELECT expires_at FROM licenses WHERE license_key=?", (key,)).fetchone()
    if row:
        base = datetime.fromisoformat(row["expires_at"]) if row["expires_at"] else datetime.now()
        conn.execute("UPDATE licenses SET expires_at=?, is_active=1 WHERE license_key=?",
                     ((base + timedelta(days=days)).isoformat(), key))
        conn.commit()
    conn.close()

init_db()
