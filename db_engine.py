"""
محرك قاعدة البيانات - نظام العادل v7
يدعم SQL Server (شبكة) + SQLite (محلي للإعدادات)
متوافق مع Python 3.8+
"""
import os, sqlite3, json, threading, socket
from pathlib import Path
from datetime import datetime

BASE_DIR  = Path(__file__).parent
LOCAL_DB  = BASE_DIR / "database" / "local_settings.db"
LOCAL_DB.parent.mkdir(parents=True, exist_ok=True)

_lock = threading.Lock()

# ══════════════════════════════════════════════════════
#  SQLite المحلي
# ══════════════════════════════════════════════════════
def local_conn():
    conn = sqlite3.connect(str(LOCAL_DB), timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

def init_local_db():
    conn = local_conn()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS local_config (
        [key]   TEXT PRIMARY KEY,
        [value] TEXT
    );
    CREATE TABLE IF NOT EXISTS ministries (
        id   INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL
    );
    CREATE TABLE IF NOT EXISTS departments (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        ministry_id INTEGER NOT NULL,
        name        TEXT NOT NULL,
        identifier  TEXT DEFAULT '',
        FOREIGN KEY(ministry_id) REFERENCES ministries(id) ON DELETE CASCADE
    );
    """)
    try:
        conn.execute("ALTER TABLE departments ADD COLUMN identifier TEXT DEFAULT ''")
    except: pass
    conn.commit()
    conn.close()

# ══════════════════════════════════════════════════════
#  SQL Server - اكتشاف الـ Driver تلقائياً
# ══════════════════════════════════════════════════════

# قائمة كاملة بكل الـ drivers المعروفة مرتبة من الأحدث للأقدم
ALL_SQL_DRIVERS = [
    "ODBC Driver 18 for SQL Server",
    "ODBC Driver 17 for SQL Server",
    "ODBC Driver 13.1 for SQL Server",
    "ODBC Driver 13 for SQL Server",
    "ODBC Driver 11 for SQL Server",
    "SQL Server Native Client 11.0",
    "SQL Server Native Client 10.0",
    "SQL Server",
]

def get_available_drivers():
    """الحصول على قائمة الـ drivers المثبتة فعلياً"""
    try:
        import pyodbc
        installed = pyodbc.drivers()
        # إرجاع المتاحة بنفس الترتيب المفضل
        found = [d for d in ALL_SQL_DRIVERS if d in installed]
        # أضف أي driver يحتوي على SQL Server لم نعرفه
        for d in installed:
            if "SQL Server" in d and d not in found:
                found.append(d)
        return found
    except ImportError:
        return []

def get_best_driver():
    """أفضل driver متاح"""
    drivers = get_available_drivers()
    return drivers[0] if drivers else None

def get_sql_config() -> dict:
    conn = local_conn()
    row  = conn.execute(
        "SELECT [value] FROM local_config WHERE [key]='sql_config'").fetchone()
    conn.close()
    return json.loads(row["value"]) if row else {}

def save_sql_config(cfg: dict):
    conn = local_conn()
    conn.execute(
        "INSERT OR REPLACE INTO local_config([key],[value]) VALUES(?,?)",
        ("sql_config", json.dumps(cfg, ensure_ascii=False)))
    conn.commit()
    conn.close()

def _build_conn_str(cfg: dict, driver: str) -> str:
    """
    بناء connection string متوافق مع كل إصدارات الـ Driver
    - Driver 18: يحتاج TrustServerCertificate=yes و Encrypt=yes/no
    - Driver 17: يدعم TrustServerCertificate
    - Driver القديمة (SQL Server, Native Client): لا تدعم هذه الخصائص
    """
    server   = cfg.get("server", "").strip()
    database = cfg.get("database", "AdilSystem").strip()
    username = cfg.get("username", "sa").strip()
    password = cfg.get("password", "")

    is_new_driver = ("17" in driver or "18" in driver)
    is_v18        = "18" in driver

    if is_new_driver:
        # Driver 17 و 18 - يدعمان TrustServerCertificate
        parts = [
            "DRIVER={" + driver + "}",
            "SERVER=" + server,
            "DATABASE=" + database,
            "UID=" + username,
            "PWD=" + password,
            "TrustServerCertificate=yes",
            "Connection Timeout=15",
        ]
        # Driver 18 يحتاج Encrypt صريح
        if is_v18:
            parts.append("Encrypt=Optional")
    else:
        # Driver قديمة (SQL Server, Native Client) - connection string بسيط
        parts = [
            "DRIVER={" + driver + "}",
            "SERVER=" + server,
            "DATABASE=" + database,
            "UID=" + username,
            "PWD=" + password,
            "Connection Timeout=15",
        ]

    return ";".join(parts) + ";"

def sql_conn():
    """اتصال SQL Server مع تجربة كل الـ drivers المتاحة"""
    cfg = get_sql_config()
    if not cfg:
        raise Exception("لم يتم تكوين اتصال SQL Server - افتح صفحة الإعداد")

    try:
        import pyodbc
    except ImportError:
        raise Exception(
            "مكتبة pyodbc غير مثبتة. شغّل: install_requirements.bat")

    drivers = get_available_drivers()
    if not drivers:
        raise Exception(
            "لا يوجد ODBC Driver لـ SQL Server.\n"
            "حمّل من: https://aka.ms/downloadmsodbcsql\n"
            "(ODBC Driver 17 or 18 for SQL Server)")

    last_err = None
    for drv in drivers:
        try:
            cs = _build_conn_str(cfg, drv)
            c  = pyodbc.connect(cs, timeout=15)
            return c
        except Exception as e:
            last_err = e
            continue

    raise Exception(
        "فشل الاتصال بـ SQL Server.\n"
        "السبب: {err}\n"
        "تأكد من:\n"
        "1. أن SQL Server يعمل\n"
        "2. أن TCP/IP مفعّل في SQL Server Configuration Manager\n"
        "3. أن الـ Firewall يسمح بالبورت 1433\n"
        "4. صحة اسم المستخدم وكلمة المرور".format(err=str(last_err))
    )

def test_sql_connection(cfg: dict) -> dict:
    """اختبار شامل للاتصال مع تشخيص دقيق"""
    try:
        import pyodbc
    except ImportError:
        return {
            "success": False,
            "message": "مكتبة pyodbc غير مثبتة",
            "fix": "شغّل install_requirements.bat"
        }

    all_installed = pyodbc.drivers()
    sql_drivers   = [d for d in all_installed if "SQL Server" in d]
    available     = get_available_drivers()

    if not available:
        return {
            "success":   False,
            "message":   "لا يوجد ODBC Driver لـ SQL Server مثبت",
            "installed": all_installed,
            "fix":       "حمّل ODBC Driver 17 من: https://aka.ms/downloadmsodbcsql"
        }

    errors = []
    for drv in available:
        try:
            cs = _build_conn_str(cfg, drv)
            c  = pyodbc.connect(cs, timeout=10)
            ver = c.execute("SELECT @@VERSION").fetchone()[0].split('\n')[0]
            c.close()
            return {
                "success":   True,
                "version":   ver,
                "driver":    drv,
                "available": available
            }
        except Exception as e:
            err_str = str(e)
            errors.append({"driver": drv, "error": err_str})

            # تشخيص دقيق بناءً على رقم الخطأ
            if "18456" in err_str:
                # خطأ تسجيل الدخول - نتوقف هنا لأن المشكلة في بيانات المستخدم
                fix = (
                    "خطأ في اسم المستخدم أو كلمة المرور (18456)\n\n"
                    "الحل في SSMS:\n"
                    "1. Security → Logins → sa → كليك يمين → Properties\n"
                    "2. General: تأكد من كلمة المرور\n"
                    "3. Status: Login = Enabled\n"
                    "4. كليك يمين على السيرفر → Properties → Security\n"
                    "   → SQL Server and Windows Authentication mode\n"
                    "5. أعد تشغيل SQL Server Service"
                )
                return {
                    "success":  False,
                    "message":  "Login failed for user - خطأ في اسم المستخدم أو كلمة المرور",
                    "error_code": "18456",
                    "driver_used": drv,
                    "tried":    available,
                    "fix":      fix
                }
            elif "08001" in err_str or "10060" in err_str or "10061" in err_str:
                # خطأ شبكة - السيرفر غير متاح
                fix = (
                    "السيرفر غير متاح على الشبكة\n\n"
                    "تحقق من:\n"
                    "1. SQL Server Configuration Manager → TCP/IP → Enable\n"
                    "2. TCP Port = 1433\n"
                    "3. SQL Server Browser Service يعمل\n"
                    "4. Windows Firewall → Port 1433 مفتوح\n"
                    "5. SQL Server Service يعمل"
                )
                return {
                    "success":    False,
                    "message":    "Cannot connect to server - السيرفر غير متاح",
                    "error_code": "network",
                    "driver_used": drv,
                    "fix":        fix
                }
            continue

    # إذا فشلت كل المحاولات
    last_error = errors[-1]["error"] if errors else "خطأ غير معروف"
    return {
        "success":  False,
        "message":  last_error,
        "tried":    available,
        "errors":   errors,
        "fix": (
            "تحقق من:\n"
            "1. Mixed Mode Authentication مفعّل في SSMS → Server Properties → Security\n"
            "2. SA Login مفعّل: Security → Logins → sa → Properties → Status = Enabled\n"
            "3. TCP/IP مفعّل في SQL Server Configuration Manager\n"
            "4. Port 1433 مفتوح في Firewall\n"
            "5. أعد تشغيل SQL Server بعد أي تغيير"
        )
    }

# ══════════════════════════════════════════════════════
#  إنشاء جداول SQL Server
# ══════════════════════════════════════════════════════
def init_sql_server_db():
    conn = sql_conn()
    cur  = conn.cursor()

    # كل جملة منفصلة لتجنب مشاكل GO في pyodbc
    stmts = [
        """
        IF NOT EXISTS (
            SELECT * FROM sysobjects WHERE name='distribution_files' AND xtype='U')
        CREATE TABLE distribution_files (
            [id]                INT IDENTITY(1,1) PRIMARY KEY,
            [file_code]         NVARCHAR(60)  NOT NULL,
            [system_type]       NVARCHAR(10)  NOT NULL,
            [min_name]          NVARCHAR(200),
            [dept_name]         NVARCHAR(200),
            [identifier]        NVARCHAR(60),
            [filter_month]      INT,
            [filter_year]       INT,
            [label]             NVARCHAR(500),
            [total_distributed] FLOAT DEFAULT 0,
            [rows_count]        INT   DEFAULT 0,
            [created_at]        DATETIME DEFAULT GETDATE(),
            [created_by]        NVARCHAR(100),
            [machine_name]      NVARCHAR(100),
            [is_completed]      BIT DEFAULT 0,
            CONSTRAINT UQ_file_sys UNIQUE([file_code], [system_type])
        )
        """,
        """
        IF NOT EXISTS (
            SELECT * FROM sysobjects WHERE name='distribution_details' AND xtype='U')
        CREATE TABLE distribution_details (
            [id]           INT IDENTITY(1,1) PRIMARY KEY,
            [file_id]      INT NOT NULL,
            [client_code]  NVARCHAR(100),
            [invoice_id]   NVARCHAR(100),
            [invoice_date] NVARCHAR(60),
            [sort_value]   NVARCHAR(100),
            [sap_code]     NVARCHAR(100),
            [sap_number]   NVARCHAR(100),
            [installment_number] NVARCHAR(100),
            [original_rem] FLOAT,
            [distributed]  FLOAT,
            [remaining]    FLOAT,
            [status]       NVARCHAR(60),
            [extra_data]   NVARCHAR(MAX),
            FOREIGN KEY([file_id]) REFERENCES distribution_files([id]) ON DELETE CASCADE
        )
        """,
        """
        IF NOT EXISTS (
            SELECT * FROM sysobjects WHERE name='diff_completed' AND xtype='U')
        CREATE TABLE diff_completed (
            [id]           INT IDENTITY(1,1) PRIMARY KEY,
            [file_code]    NVARCHAR(60),
            [adil_file_id] INT,
            [sap_file_id]  INT,
            [completed_at] DATETIME DEFAULT GETDATE(),
            [completed_by] NVARCHAR(100),
            [notes]        NVARCHAR(MAX)
        )
        """,
        """
        IF NOT EXISTS (
            SELECT * FROM sysobjects WHERE name='shared_config' AND xtype='U')
        CREATE TABLE shared_config (
            [key]   NVARCHAR(200) PRIMARY KEY,
            [value] NVARCHAR(MAX)
        )
        """
    ]

    for stmt in stmts:
        cur.execute(stmt)
        conn.commit()

    # ترحيل الجداول التي أنشأتها الإصدارات السابقة.
    for column, definition in (
        ("sap_code", "NVARCHAR(100)"),
        ("sap_number", "NVARCHAR(100)"),
        ("installment_number", "NVARCHAR(100)"),
    ):
        cur.execute(
            "IF COL_LENGTH('distribution_details', ?) IS NULL "
            "ALTER TABLE distribution_details ADD [" + column + "] " + definition,
            ("distribution_details." + column,))
        conn.commit()

    conn.commit()
    conn.close()
    return True

# ══════════════════════════════════════════════════════
#  بناء رمز الملف
# ══════════════════════════════════════════════════════
def build_file_code(system_type: str, year: int, month: int, identifier: str) -> str:
    prefix = "A" if system_type == "Adil" else "S"
    mm     = str(month).zfill(2)
    return "{prefix}{year}{mm}{identifier}".format(
        prefix=prefix, year=year, mm=mm, identifier=identifier)

# ══════════════════════════════════════════════════════
#  عمليات الملفات
# ══════════════════════════════════════════════════════
def check_file_exists(file_code: str, system_type: str) -> dict:
    try:
        conn = sql_conn()
        row  = conn.execute(
            "SELECT [id], [total_distributed], [rows_count], [created_at], [label], [created_by] "
            "FROM distribution_files "
            "WHERE [file_code]=? AND [system_type]=?",
            (file_code, system_type)).fetchone()
        conn.close()
        if row:
            return {
                "exists":     True,
                "file_id":    row[0],
                "total":      row[1],
                "rows":       row[2],
                "created_at": str(row[3]),
                "label":      row[4],
                "created_by": row[5]
            }
        return {"exists": False}
    except Exception as e:
        return {"exists": False, "error": str(e)}

def save_distribution(file_code, system_type, min_name, dept_name, identifier,
                      filter_month, filter_year, label, rows_data, columns,
                      total_dist, c2_code, c2_invoice, c2_invdate, c2_sort,
                      c2_rem, extra_cols, append_to_id=None) -> int:

    machine = socket.gethostname()
    conn    = sql_conn()
    cur     = conn.cursor()

    # تحديث قواعد البيانات القديمة قبل أول عملية حفظ.
    for column in ("sap_code", "sap_number", "installment_number"):
        cur.execute(
            "IF COL_LENGTH('distribution_details', '" + column + "') IS NULL "
            "ALTER TABLE distribution_details ADD [" + column + "] NVARCHAR(100)"
        )
    conn.commit()

    if append_to_id:
        file_id = append_to_id
        cur.execute(
            "UPDATE distribution_files "
            "SET [rows_count]=[rows_count]+?, [total_distributed]=[total_distributed]+? "
            "WHERE [id]=?",
            (len(rows_data), total_dist, file_id))
    else:
        cur.execute(
            "INSERT INTO distribution_files "
            "([file_code],[system_type],[min_name],[dept_name],[identifier],"
            "[filter_month],[filter_year],[label],[total_distributed],[rows_count],"
            "[created_by],[machine_name]) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (file_code, system_type, min_name, dept_name, identifier,
             filter_month, filter_year, label, total_dist, len(rows_data),
             machine, machine))
        conn.commit()
        row = cur.execute(
            "SELECT [id] FROM distribution_files "
            "WHERE [file_code]=? AND [system_type]=?",
            (file_code, system_type)).fetchone()
        file_id = row[0]

    # بناء خريطة الأعمدة
    row_map = {c: i for i, c in enumerate(columns)}

    skip = {c2_code, c2_invoice, c2_invdate, c2_sort, c2_rem,
            "عمود توزيع الاقساط", "المتبقي بعد التوزيع",
            "الحالة", "الجهة"}

    for row in rows_data:
        extra = {}
        for col in columns:
            if col not in skip:
                idx = row_map.get(col)
                extra[col] = row[idx] if idx is not None else ""

        def safe(col, default=0):
            idx = row_map.get(col)
            if idx is None:
                return default
            v = row[idx]
            try:
                return float(v) if v != "" else default
            except:
                return default

        def safe_str(col):
            idx = row_map.get(col)
            if idx is None or row[idx] == "":
                return ""
            value = row[idx]
            if hasattr(value, "to_pydatetime"):
                value = value.to_pydatetime()
            if isinstance(value, datetime):
                return value.date().isoformat()
            return str(value)

        client_code = safe_str(c2_code)
        invoice_id = safe_str(c2_invoice)
        invoice_date = safe_str(c2_invdate)
        sort_value = safe_str(c2_sort)
        sap_code = client_code if system_type == "SAP" else ""
        sap_number = invoice_id if system_type == "SAP" else ""
        installment_number = sort_value if system_type == "SAP" else ""

        cur.execute(
            "INSERT INTO distribution_details "
            "([file_id],[client_code],[invoice_id],[invoice_date],[sort_value],"
            "[sap_code],[sap_number],[installment_number],"
            "[original_rem],[distributed],[remaining],[status],[extra_data]) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                file_id,
                client_code,
                invoice_id,
                invoice_date,
                sort_value,
                sap_code,
                sap_number,
                installment_number,
                safe(c2_rem),
                safe("عمود توزيع الاقساط"),
                safe("المتبقي بعد التوزيع"),
                safe_str("الحالة"),
                json.dumps(extra, ensure_ascii=False)
            ))

    conn.commit()
    conn.close()
    return file_id

def get_files_list(system_type=None) -> list:
    try:
        conn = sql_conn()
        q    = (
            "SELECT [id],[file_code],[system_type],[label],"
            "[total_distributed],[rows_count],[created_at],[created_by],[is_completed] "
            "FROM distribution_files"
        )
        args = ()
        if system_type:
            q    += " WHERE [system_type]=?"
            args  = (system_type,)
        q += " ORDER BY created_at DESC"
        rows = conn.execute(q, args).fetchall()
        conn.close()
        return [
            {
                "id":          r[0],
                "file_code":   r[1],
                "system_type": r[2],
                "label":       r[3],
                "total":       r[4],
                "rows":        r[5],
                "created_at":  str(r[6])[:16],
                "created_by":  r[7],
                "completed":   bool(r[8])
            }
            for r in rows
        ]
    except Exception as e:
        return []

def get_file_details(file_id: int) -> list:
    conn = sql_conn()
    rows = conn.execute(
        "SELECT [client_code],[invoice_id],[invoice_date],[sort_value],"
        "[original_rem],[distributed],[remaining],[status],[extra_data] "
        "FROM distribution_details "
        "WHERE [file_id]=? "
        "ORDER BY [client_code],[invoice_id],[sort_value]",
        (file_id,)).fetchall()
    conn.close()
    result = []
    for r in rows:
        extra = json.loads(r[8]) if r[8] else {}
        result.append({
            "client_code":  r[0],
            "invoice_id":   r[1],
            "invoice_date": r[2],
            "sort_value":   r[3],
            "original_rem": r[4],
            "distributed":  r[5],
            "remaining":    r[6],
            "status":       r[7],
            "extra":        extra
        })
    return result

def delete_distribution(file_id: int) -> bool:
    conn = sql_conn()
    try:
        cursor = conn.execute("DELETE FROM distribution_files WHERE [id]=?", (file_id,))
        if cursor.rowcount == 0:
            conn.rollback()
            return False
        conn.commit()
        return True
    finally:
        conn.close()

def get_diff_pairs() -> list:
    try:
        conn = sql_conn()
        rows = conn.execute("""
            SELECT a.[id], s.[id], a.[file_code], a.[label],
                   a.[total_distributed], s.[total_distributed],
                   a.[rows_count], s.[rows_count]
            FROM distribution_files a
            JOIN distribution_files s
                ON SUBSTRING(a.file_code, 2, LEN(a.file_code)) =
                   SUBSTRING(s.file_code, 2, LEN(s.file_code))
            WHERE a.system_type='Adil' AND s.system_type='SAP'
              AND SUBSTRING(a.file_code, 2, LEN(a.file_code)) NOT IN (
                  SELECT file_code FROM diff_completed
              )
        """).fetchall()
        conn.close()
        return [
            {
                "adil_id":    r[0],
                "sap_id":     r[1],
                "file_code":  r[2][1:],
                "label":      r[3],
                "adil_total": r[4],
                "sap_total":  r[5],
                "adil_rows":  r[6],
                "sap_rows":   r[7]
            }
            for r in rows
        ]
    except Exception as e:
        return []

def get_diff_details(adil_id: int, sap_id: int) -> list:
    conn = sql_conn()

    def fetch(fid):
        return {
            (r[0], r[1], r[2]): r
            for r in conn.execute(
                "SELECT [client_code],[invoice_id],[sort_value],"
                "[original_rem],[distributed],[remaining],[status],[extra_data] "
                "FROM distribution_details WHERE [file_id]=?",
                (fid,)).fetchall()
        }

    adil_rows = fetch(adil_id)
    sap_rows  = fetch(sap_id)
    conn.close()

    all_keys = set(adil_rows.keys()) | set(sap_rows.keys())
    diffs    = []

    for key in sorted(all_keys):
        a = adil_rows.get(key)
        s = sap_rows.get(key)
        adil_dist = float(a[4]) if a else 0
        sap_dist  = float(s[4]) if s else 0
        diff      = round(adil_dist - sap_dist, 2)
        src       = a or s
        extra     = json.loads(src[7]) if src[7] else {}

        diffs.append({
            "client_code":  key[0],
            "invoice_id":   key[1],
            "sort_value":   key[2],
            "adil_dist":    adil_dist,
            "sap_dist":     sap_dist,
            "diff":         diff,
            "adil_status":  a[6] if a else "غير موجود",
            "sap_status":   s[6] if s else "غير موجود",
            "extra":        extra,
            "has_diff":     diff != 0
        })

    return diffs

def mark_diff_completed(file_code: str, adil_id: int,
                        sap_id: int, notes: str = ""):
    machine = socket.gethostname()
    conn    = sql_conn()
    conn.execute(
        "INSERT INTO diff_completed"
        "([file_code],[adil_file_id],[sap_file_id],[completed_by],[notes]) "
        "VALUES(?,?,?,?,?)",
        (file_code, adil_id, sap_id, machine, notes))
    conn.commit()
    conn.close()

def get_diff_completed() -> list:
    try:
        conn = sql_conn()
        rows = conn.execute("""
            SELECT dc.[id], dc.[file_code], df.[label], dc.[completed_at],
                   dc.[completed_by], dc.[notes],
                   a.[total_distributed], s.[total_distributed]
            FROM diff_completed dc
            LEFT JOIN distribution_files a ON dc.adil_file_id = a.id
            LEFT JOIN distribution_files s ON dc.sap_file_id  = s.id
            LEFT JOIN distribution_files df
                ON df.file_code = 'A' + dc.file_code
               AND df.system_type = 'Adil'
            ORDER BY dc.completed_at DESC
        """).fetchall()
        conn.close()
        return [
            {
                "id":           r[0],
                "file_code":    r[1],
                "label":        r[2],
                "completed_at": str(r[3])[:16],
                "completed_by": r[4],
                "notes":        r[5],
                "adil_total":   r[6],
                "sap_total":    r[7]
            }
            for r in rows
        ]
    except:
        return []

# تهيئة SQLite المحلي عند الاستيراد
init_local_db()
