"""
نظام العادل لتوزيع الأقساط - v7
SQL Server (مركزي) + SQLite (محلي)
"""
import os, json, sqlite3, webbrowser, threading, time, re, socket, zipfile
from pathlib import Path
from datetime import datetime
import pandas as pd
from fastapi import FastAPI, UploadFile, File, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from license_engine import (verify_license, activate_license, generate_license_key,
                             admin_list_licenses, admin_toggle_license, admin_delete_license,
                             admin_extend_license, get_hardware_id)
from db_engine import (
    local_conn, init_local_db, get_sql_config, save_sql_config,
    test_sql_connection, init_sql_server_db, build_file_code,
    check_file_exists, save_distribution, get_files_list, get_file_details,
    get_diff_pairs, get_diff_details, mark_diff_completed, get_diff_completed
    , delete_distribution
)

BASE_DIR   = Path(__file__).parent
UPLOAD_DIR = BASE_DIR / "database" / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="نظام العادل v7")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.mount("/static", StaticFiles(directory=str(BASE_DIR/"static")), name="static")

# ── Pages ──────────────────────────────────────────────────────────────────────
OPEN = {"/","/activate","/admin","/api/activate","/api/license-status",
    "/api/admin","/api/hardware-id","/api/sql-config","/api/sql-test",
    "/api/sql-ready","/api/sql-init"}

@app.middleware("http")
async def lic_mw(request: Request, call_next):
    path = request.url.path
    if any(path.startswith(p) for p in OPEN) or path.startswith("/static"):
        return await call_next(request)
    r = verify_license()
    if not r["valid"]:
        return JSONResponse({"error":"license_invalid","message":r["message"]}, status_code=403)
    return await call_next(request)

@app.get("/",      response_class=HTMLResponse)
async def pg_login(): return open(BASE_DIR/"static"/"login.html",  encoding="utf-8").read()
@app.get("/app",   response_class=HTMLResponse)
async def pg_app():   return open(BASE_DIR/"static"/"index.html",  encoding="utf-8").read()
@app.get("/admin", response_class=HTMLResponse)
async def pg_admin(): return open(BASE_DIR/"static"/"admin.html",  encoding="utf-8").read()
@app.get("/setup", response_class=HTMLResponse)
async def pg_setup(): return open(BASE_DIR/"static"/"setup.html",  encoding="utf-8").read()
@app.get("/history",response_class=HTMLResponse)
async def pg_hist():  return open(BASE_DIR/"static"/"history.html",encoding="utf-8").read()
@app.get("/diff",  response_class=HTMLResponse)
async def pg_diff():  return open(BASE_DIR/"static"/"diff.html",   encoding="utf-8").read()

# ── License ────────────────────────────────────────────────────────────────────
@app.get("/api/license-status")
async def lic_status(): return verify_license()
@app.get("/api/hardware-id")
async def hw_id(): return {"hw_id": get_hardware_id()}
@app.post("/api/activate")
async def api_activate(data: dict):
    k = data.get("key","").strip()
    if not k: raise HTTPException(400,"مفتاح مطلوب")
    return activate_license(k)

ADMIN_PASSWORD = "ADIL@ADMIN2024"
@app.post("/api/admin/auth")
async def admin_auth(data: dict):
    if data.get("password") == ADMIN_PASSWORD:
        return {"success":True,"hw_id":get_hardware_id()}
    raise HTTPException(403,"كلمة مرور غير صحيحة")
@app.get("/api/admin/licenses")  
async def admin_lics(): return admin_list_licenses()
@app.post("/api/admin/generate")
async def admin_gen(d: dict):
    k=generate_license_key(d.get("client_name","عميل"),d.get("license_type","monthly"),d.get("duration_days"),d.get("notes",""))
    return {"success":True,"key":k}
@app.post("/api/admin/toggle")
async def admin_tog(d: dict): admin_toggle_license(d["key"],d["active"]); return {"success":True}
@app.post("/api/admin/delete")
async def admin_del(d: dict): admin_delete_license(d["key"]); return {"success":True}
@app.post("/api/admin/extend")
async def admin_ext(d: dict): admin_extend_license(d["key"],d.get("days",30)); return {"success":True}

# ── SQL Server Config ──────────────────────────────────────────────────────────
@app.get("/api/sql-config")
async def get_sql_cfg():
    cfg = get_sql_config()
    if cfg: cfg.pop("password", None)
    return {"configured": bool(cfg), "config": cfg}

@app.post("/api/sql-config")
async def set_sql_cfg(data: dict):
    save_sql_config(data)
    return {"success": True}
@app.get("/api/sql-drivers")
async def sql_drivers():
    """قائمة ODBC Drivers المتاحة - استجابة سريعة"""
    import asyncio, concurrent.futures

    def _get_drivers():
        try:
            import pyodbc
            all_d = pyodbc.drivers()
            sql_d = [d for d in all_d if "SQL Server" in d]
            # ترتيب المفضل
            preferred = [
                "ODBC Driver 18 for SQL Server",
                "ODBC Driver 17 for SQL Server",
                "ODBC Driver 13.1 for SQL Server",
                "ODBC Driver 13 for SQL Server",
                "ODBC Driver 11 for SQL Server",
                "SQL Server Native Client 11.0",
                "SQL Server Native Client 10.0",
                "SQL Server",
            ]
            avail = [d for d in preferred if d in all_d]
            for d in all_d:
                if "SQL Server" in d and d not in avail:
                    avail.append(d)
            return {"drivers": avail, "all_drivers": all_d, "sql_drivers": sql_d}
        except ImportError:
            return {"drivers": [], "all_drivers": [], "error": "pyodbc not installed"}
        except Exception as e:
            return {"drivers": [], "all_drivers": [], "error": str(e)}

    try:
        loop = asyncio.get_event_loop()
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            # timeout 5 ثواني
            result = await asyncio.wait_for(
                loop.run_in_executor(pool, _get_drivers),
                timeout=5.0
            )
        return result
    except asyncio.TimeoutError:
        return {"drivers": [], "all_drivers": [], "error": "timeout - pyodbc slow"}
    except Exception as e:
        return {"drivers": [], "all_drivers": [], "error": str(e)}



@app.post("/api/sql-test")
async def sql_test(data: dict):
    return test_sql_connection(data)

@app.get("/api/sql-ready")
async def sql_ready():
    """فحص الاتصال بالإعدادات المحفوظة قبل فتح التطبيق."""
    cfg = get_sql_config()
    if not cfg:
        return {"ready": False, "reason": "not_configured"}
    result = test_sql_connection(cfg)
    return {
        "ready": bool(result.get("success")),
        "reason": "connected" if result.get("success") else "connection_failed",
        "message": result.get("message", "")
    }

@app.post("/api/sql-init")
async def sql_init():
    try:
        init_sql_server_db()
        return {"success": True, "message": "تم إنشاء جداول قاعدة البيانات بنجاح"}
    except Exception as e:
        raise HTTPException(500, str(e))

# ── Local Config ───────────────────────────────────────────────────────────────
@app.get("/api/config")
async def get_cfg():
    conn = local_conn()
    rows = conn.execute("SELECT [key],[value] FROM local_config").fetchall()
    conn.close()
    return {r["key"]: json.loads(r["value"]) for r in rows}

@app.post("/api/config")
async def save_cfg(data: dict):
    conn = local_conn()
    for k,v in data.items():
        conn.execute("INSERT OR REPLACE INTO local_config([key],[value]) VALUES(?,?)",
                     (k, json.dumps(v, ensure_ascii=False)))
    conn.commit(); conn.close()
    return {"success": True}

# ── Ministries ─────────────────────────────────────────────────────────────────
@app.get("/api/ministries")
async def get_ministries():
    conn = local_conn()
    mins = conn.execute("SELECT id,[name] FROM ministries ORDER BY [name]").fetchall()
    result = []
    for m in mins:
        depts = conn.execute(
            "SELECT id,[name],[identifier] FROM departments WHERE ministry_id=? ORDER BY [name]",
            (m["id"],)).fetchall()
        result.append({"id":m["id"],"name":m["name"],
                       "departments":[{"id":d["id"],"name":d["name"],
                                       "identifier":d["identifier"]or""} for d in depts]})
    conn.close()
    return result

@app.post("/api/ministries")
async def add_ministry(data: dict):
    name = data.get("name","").strip()
    if not name: raise HTTPException(400,"الاسم مطلوب")
    conn = local_conn()
    try:
        conn.execute("INSERT INTO ministries([name]) VALUES(?)",(name,))
        conn.commit()
        mid = conn.execute("SELECT id FROM ministries WHERE [name]=?",(name,)).fetchone()["id"]
        conn.close(); return {"success":True,"id":mid}
    except: conn.close(); raise HTTPException(400,"موجود مسبقاً")

@app.put("/api/ministries/{mid}")
async def upd_ministry(mid:int, data:dict):
    conn=local_conn(); conn.execute("UPDATE ministries SET [name]=? WHERE id=?",(data["name"],mid))
    conn.commit(); conn.close(); return {"success":True}

@app.delete("/api/ministries/{mid}")
async def del_ministry(mid:int):
    conn=local_conn(); conn.execute("DELETE FROM ministries WHERE id=?",(mid,))
    conn.commit(); conn.close(); return {"success":True}

@app.post("/api/departments")
async def add_dept(data:dict):
    conn=local_conn()
    conn.execute("INSERT INTO departments(ministry_id,[name],[identifier]) VALUES(?,?,?)",
                 (data["ministry_id"],data["name"].strip(),data.get("identifier","").strip()))
    conn.commit(); conn.close(); return {"success":True}

@app.put("/api/departments/{did}")
async def upd_dept(did:int,data:dict):
    conn=local_conn()
    conn.execute("UPDATE departments SET [name]=?,[identifier]=? WHERE id=?",(data["name"],data.get("identifier",""),did))
    conn.commit(); conn.close(); return {"success":True}

@app.delete("/api/departments/{did}")
async def del_dept(did:int):
    conn=local_conn(); conn.execute("DELETE FROM departments WHERE id=?",(did,))
    conn.commit(); conn.close(); return {"success":True}

@app.get("/api/ministries/export")
async def export_ministries():
    conn = local_conn()
    mins = conn.execute("SELECT id,name FROM ministries").fetchall()
    rows = []
    for m in mins:
        depts = conn.execute("SELECT [name],[identifier] FROM departments WHERE ministry_id=?",(m["id"],)).fetchall()
        if depts:
            for d in depts: rows.append({"الوزارة":m["name"],"القسم":d["name"],"المعرف":d["identifier"]or""})
        else: rows.append({"الوزارة":m["name"],"القسم":"","المعرف":""})
    conn.close()
    df  = pd.DataFrame(rows) if rows else pd.DataFrame(columns=["الوزارة","القسم","المعرف"])
    out = UPLOAD_DIR/"ministries_export.xlsx"
    df.to_excel(out,index=False)
    return FileResponse(str(out),filename="قائمة_الوزارات_والأقسام.xlsx",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

@app.post("/api/ministries/import")
async def import_ministries(file: UploadFile = File(...)):
    ext = Path(file.filename).suffix.lower()
    tmp = UPLOAD_DIR/f"min_import{ext}"
    tmp.write_bytes(await file.read())
    try:
        df = pd.read_csv(tmp) if ext==".csv" else pd.read_excel(tmp)
        df.columns = [str(c).strip() for c in df.columns]
        for r in ["الوزارة","القسم","المعرف"]:
            if r not in df.columns: raise HTTPException(400,f"العمود '{r}' غير موجود")
        conn = local_conn(); added_m=0; added_d=0
        for _,row in df.iterrows():
            mn=str(row["الوزارة"]).strip(); dn=str(row["القسم"]).strip()
            ident=str(row["المعرف"]).strip() if str(row["المعرف"]) not in("nan","") else ""
            if not mn or mn=="nan": continue
            ex=conn.execute("SELECT id FROM ministries WHERE [name]=?",(mn,)).fetchone()
            if ex: mid=ex["id"]
            else:
                conn.execute("INSERT INTO ministries([name]) VALUES(?)",(mn,)); conn.commit()
                mid=conn.execute("SELECT id FROM ministries WHERE [name]=?",(mn,)).fetchone()["id"]; added_m+=1
            if dn and dn!="nan":
                ex2=conn.execute("SELECT id FROM departments WHERE ministry_id=? AND [name]=?",(mid,dn)).fetchone()
                if not ex2:
                    conn.execute("INSERT INTO departments(ministry_id,[name],[identifier]) VALUES(?,?,?)",(mid,dn,ident)); added_d+=1
                else:
                    # تحديث المعرف فقط إن كان فارغاً
                    if ident:
                        conn.execute("UPDATE departments SET [identifier]=? WHERE id=? AND ([identifier]='' OR [identifier] IS NULL)",(ident,ex2["id"]))
        conn.commit(); conn.close()
        return {"success":True,"message":f"تمت الإضافة: {added_m} وزارة و {added_d} قسم جديد (البيانات القديمة محفوظة)"}
    except HTTPException: raise
    except Exception as e: raise HTTPException(400,str(e))

# ── File Upload ────────────────────────────────────────────────────────────────
def smart_parse_date(series):
    """معالجة ذكية للتواريخ - تجرب عدة صيغ"""
    formats = [
        "%Y-%m-%d","%d/%m/%Y","%m/%d/%Y","%d-%m-%Y",
        "%Y/%m/%d","%d.%m.%Y","%m-%d-%Y","%Y%m%d",
        "%d %b %Y","%d %B %Y","%b %d %Y",
    ]
    result = pd.to_datetime(series, errors="coerce", dayfirst=True)
    if result.isna().all():
        for fmt in formats:
            try:
                result = pd.to_datetime(series, format=fmt, errors="coerce")
                if not result.isna().all(): break
            except: continue
    # آخر محاولة: تحويل نصي
    if result.isna().any():
        def try_parse(v):
            if pd.isna(v): return pd.NaT
            s = str(v).strip()
            for fmt in formats:
                try: return datetime.strptime(s, fmt)
                except: continue
            return pd.NaT
        result2 = series.apply(try_parse)
        result  = result.fillna(result2)
    return result

def read_file(p):
    p=str(p)
    if p.endswith(".csv"):
        for enc in ["utf-8","utf-8-sig","cp1256","latin-1"]:
            try: return pd.read_csv(p, encoding=enc)
            except: continue
    if p.lower().endswith(".xlsx"):
        if not zipfile.is_zipfile(p):
            raise ValueError("ملف XLSX غير مكتمل أو تالف. افتحه في Excel واختر حفظ باسم XLSX ثم أعد رفعه.")
        return pd.read_excel(p, engine="openpyxl")
    if p.lower().endswith(".xls"):
        try:
            return pd.read_excel(p, engine="xlrd")
        except ImportError:
            raise ValueError("صيغة XLS تحتاج تثبيت xlrd. استخدم XLSX أو شغّل ملف التشغيل لتثبيت المتطلبات.")
    return pd.read_excel(p)

def json_safe_value(value):
    """تحويل قيم pandas إلى أنواع يمكن إرجاعها في JSON."""
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.date().isoformat()
    if pd.isna(value):
        return ""
    if hasattr(value, "item"):
        return value.item()
    return value

def json_safe_rows(rows):
    return [[json_safe_value(value) for value in row] for row in rows]

def normalize_code(value):
    """توحيد كود الربط مع الحفاظ على الأكواد النصية والأصفار البادئة."""
    if pd.isna(value):
        return ""
    return str(value).strip().casefold()

@app.post("/api/upload/{slot}")
async def upload(slot:str, file:UploadFile=File(...)):
    if slot not in("file1","file2"): raise HTTPException(400,"slot غير صحيح")
    ext=Path(file.filename).suffix.lower()
    if ext not in(".xlsx",".xls",".csv"): raise HTTPException(400,"نوع غير مدعوم")
    content = await file.read()
    if not content: raise HTTPException(400,"الملف فارغ")
    p=UPLOAD_DIR/f"{slot}{ext}"
    p.write_bytes(content)
    try:
        df=read_file(p); df.columns=[str(c).strip() for c in df.columns]
        return {"success":True,"filename":file.filename,"columns":list(df.columns),"slot":slot}
    except Exception as e: raise HTTPException(400,f"خطأ في قراءة الملف: {e}")

# ── Check File Code ────────────────────────────────────────────────────────────
@app.post("/api/check-file-code")
async def check_file_code(data: dict):
    system_type = data.get("system_type","Adil")
    identifier  = data.get("identifier","")
    month       = int(data.get("month",1))
    year        = int(data.get("year",2026))
    file_code   = build_file_code(system_type, year, month, identifier)
    result      = check_file_exists(file_code, system_type)
    result["file_code"] = file_code
    return result

# ── Round-Robin ────────────────────────────────────────────────────────────────
def rr_distribute(balance:float, inv_queues:list) -> float:
    for _ in range(10_000_000):
        if balance<=0: break
        made=False
        for q in inv_queues:
            if balance<=0: break
            while q["ptr"]<len(q["rows"]) and q["rows"][q["ptr"]]["_rem"]<=0:
                q["ptr"]+=1
            if q["ptr"]>=len(q["rows"]): continue
            item=q["rows"][q["ptr"]]
            pay=min(balance,item["_rem"])
            item["_dist"]+=pay; item["_rem"]-=pay; balance-=pay; made=True
            if item["_rem"]<=0: q["ptr"]+=1
        if not made: break
    return balance

def build_export_name(mode,year,month,min_name,dept_name,identifier,system_type):
    mm=str(month).zfill(2)
    prefix="A" if system_type=="Adil" else "S"
    return f"{prefix}{year}{mm}{identifier}.xlsx" if identifier else f"{prefix}{year}{mm}.xlsx"

# ── Main Distribution ──────────────────────────────────────────────────────────
@app.post("/api/distribute")
async def distribute(cfg: dict):
    try:
        f1p=f2p=None
        for ext in(".xlsx",".xls",".csv"):
            if(UPLOAD_DIR/f"file1{ext}").exists(): f1p=UPLOAD_DIR/f"file1{ext}"
            if(UPLOAD_DIR/f"file2{ext}").exists(): f2p=UPLOAD_DIR/f"file2{ext}"
        if not f1p or not f2p: raise HTTPException(400,"يجب رفع كلا الملفين أولاً")

        df1=read_file(f1p); df1.columns=[str(c).strip() for c in df1.columns]
        df2=read_file(f2p); df2.columns=[str(c).strip() for c in df2.columns]

        c1_code=cfg.get("c1_code"); c1_amount=cfg.get("c1_amount")
        c2_code=cfg["c2_code"]; c2_invoice=cfg["c2_invoice"]
        c2_invdate=cfg["c2_invdate"]; c2_rem=cfg["c2_rem"]; c2_sort=cfg["c2_sort"]
        filter_m=int(cfg["filter_month"]); filter_y=int(cfg["filter_year"])
        filter_day=int(cfg.get("filter_day",1))
        active_cols=cfg.get("active_cols",list(df2.columns))
        custom_cols=cfg.get("custom_cols",[])
        label=cfg.get("label",""); min_name=cfg.get("min_name","")
        dept_name=cfg.get("dept_name",""); identifier=cfg.get("identifier","")
        system_type=cfg.get("system_type","Adil")
        append_to_id=cfg.get("append_to_id")

        required = {
            "جدول المبالغ": (c1_code, c1_amount),
            "جدول الأقساط": (c2_code, c2_invoice, c2_invdate, c2_rem, c2_sort),
        }
        for name, columns in required.items():
            missing = [column or "غير محدد" for column in columns if not column]
            if missing:
                raise HTTPException(400, f"أعمدة {name} غير مكتملة: {', '.join(missing)}")
        c1_code=str(c1_code); c1_amount=str(c1_amount)

        filter_date=datetime(filter_y,filter_m,filter_day)

        balances={}
        for _,row in df1.iterrows():
            code=normalize_code(row[c1_code])
            val=pd.to_numeric(str(row[c1_amount]).replace(",",""),errors="coerce") or 0.0
            if code: balances[code]=balances.get(code,0.0)+float(val)

        # معالجة ذكية للتاريخ
        df2["_invdate_dt"]=smart_parse_date(df2[c2_invdate])
        
        # تشخيص التاريخ
        total_rows=int(len(df2)); parsed=int(df2["_invdate_dt"].notna().sum())
        filtered=df2[df2["_invdate_dt"]<=filter_date]
        
        if parsed==0:
            return {"success":False,"error":"date_parse_failed",
                    "message":f"فشل تحليل عمود التاريخ '{c2_invdate}'. يرجى التحقق من صيغة التاريخ في الملف.",
                    "sample_values":df2[c2_invdate].head(5).astype(str).tolist()}

        df2_filtered=filtered.copy()
        final_rows=[]; surplus_rows=[]; visited=set()

        def summary_row(code, distributed, remaining, status):
            row={c2_code:code,"عمود توزيع الاقساط":round(distributed,2),
                 "المتبقي بعد التوزيع":round(remaining,2),"الحالة":status}
            if label: row["الجهة"]=label
            for cc in custom_cols: row[cc["header"]]=cc["value"]
            return row

        for client_code,grp in df2_filtered.groupby(c2_code):
            cs=normalize_code(client_code); visited.add(cs)
            balance=balances.get(cs,0.0)
            if cs not in balances: continue

            if balance<=0:
                surplus_rows.append(summary_row(cs,0,0,"لا يوجد مبلغ متاح"))
                continue

            inv_queues=[]
            for inv_id,inv_grp in grp.groupby(c2_invoice):
                inv_grp_sorted=inv_grp.sort_values(by=c2_sort)
                rows=[]
                for _,r in inv_grp_sorted.iterrows():
                    rem=pd.to_numeric(str(r[c2_rem]).replace(",",""),errors="coerce") or 0.0
                    if rem>0:
                        rows.append({"_row":r,"_rem":float(rem),"_dist":0.0,"_orig":float(rem)})
                if rows:
                    inv_dt=inv_grp_sorted.iloc[0]["_invdate_dt"]
                    inv_queues.append({"inv_id":inv_id,"inv_dt":inv_dt,"rows":rows,"ptr":0})

            if not inv_queues:
                surplus_rows.append(summary_row(cs,0,balance,"لا توجد أقساط قابلة للتوزيع"))
                continue
            inv_queues.sort(key=lambda x: x["inv_dt"] if pd.notna(x["inv_dt"]) else datetime.max)
            surplus=rr_distribute(balance,inv_queues)

            for q in inv_queues:
                for item in q["rows"]:
                    if item["_dist"]<=0: continue
                    out={}
                    for col in active_cols:
                        if col in item["_row"].index: out[col]=item["_row"][col]
                    out["عمود توزيع الاقساط"]=round(item["_dist"],2)
                    out["المتبقي بعد التوزيع"]=round(item["_rem"],2)
                    out["الحالة"]="مسدد كامل" if item["_rem"]<=0 else "مسدد جزئي"
                    if label: out["الجهة"]=label
                    for cc in custom_cols: out[cc["header"]]=cc["value"]
                    final_rows.append(out)

            if surplus>0:
                surplus_rows.append(summary_row(cs,surplus,0,"الأقساط الزائدة"))

        for code,bal in balances.items():
            if code not in visited:
                status="الأسماء الغير موجودة" if bal>0 else "لا يوجد مبلغ متاح"
                surplus_rows.append(summary_row(code,bal if bal>0 else 0,0,status))

        all_rows=final_rows+surplus_rows
        if not all_rows:
            return {"success":True,"rows":[],"columns":[],"count":0,
                    "active_count":0,"surplus_count":0,
                    "date_info":{"total":total_rows,"parsed":parsed,"filtered":int(len(filtered))}}

        result_df=pd.DataFrame(all_rows).fillna("")
        
        export_name=build_export_name(cfg.get("export_name_mode","label"),
                                      filter_y,filter_m,min_name,dept_name,identifier,system_type)
        result_path=UPLOAD_DIR/"result.xlsx"
        result_df.to_excel(result_path,index=False)

        # حفظ في SQL Server
        file_code=build_file_code(system_type,filter_y,filter_m,identifier)
        file_id=None
        try:
            total_dist=sum(r.get("عمود توزيع الاقساط",0) for r in final_rows)
            cols=list(result_df.columns)
            rows_for_db=result_df.values.tolist()
            file_id=save_distribution(
                file_code,system_type,min_name,dept_name,identifier,
                filter_m,filter_y,label,rows_for_db,cols,total_dist,
                c2_code,c2_invoice,c2_invdate,c2_sort,c2_rem,[],append_to_id)
        except Exception as e:
            print(f"[DB save warning] {e}")

        conn=local_conn()
        conn.execute("INSERT OR REPLACE INTO local_config([key],[value]) VALUES(?,?)",
                     ("export_name",json.dumps(export_name,ensure_ascii=False)))
        conn.commit(); conn.close()

        return {"success":True,
            "rows":json_safe_rows(result_df.values.tolist()),
                "columns":list(result_df.columns),
                "count":len(result_df),
                "active_count":len(final_rows),
                "surplus_count":len(surplus_rows),
                "export_name":export_name,
                "file_code":file_code,
                "file_id":file_id,
                "date_info":{"total":total_rows,"parsed":parsed,"filtered":int(len(filtered))}}

    except HTTPException: raise
    except Exception as e:
        import traceback; traceback.print_exc()
        raise HTTPException(500,f"خطأ: {str(e)}")

@app.get("/api/export")
async def export():
    conn=local_conn()
    row=conn.execute("SELECT [value] FROM local_config WHERE [key]='export_name'").fetchone()
    conn.close()
    name=json.loads(row["value"]) if row else "توزيع_الاقساط.xlsx"
    p=UPLOAD_DIR/"result.xlsx"
    if not p.exists(): raise HTTPException(404,"لا توجد نتائج")
    return FileResponse(str(p),filename=name,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

# ── History API ────────────────────────────────────────────────────────────────
@app.get("/api/history")
async def get_history(system_type: str = None):
    return get_files_list(system_type)

@app.get("/api/history/{file_id}")
async def get_history_detail(file_id: int):
    return get_file_details(file_id)

@app.delete("/api/history/{file_id}")
async def delete_history(file_id: int):
    try:
        if not delete_distribution(file_id):
            raise HTTPException(404, "الملف غير موجود")
        return {"success": True}
    except HTTPException: raise
    except Exception as e:
        raise HTTPException(500, f"تعذر حذف الملف: {e}")

@app.get("/api/history/{file_id}/export")
async def export_history(file_id: int):
    files = get_files_list()
    file = next((item for item in files if item["id"] == file_id), None)
    if not file: raise HTTPException(404,"الملف غير موجود")
    rows = get_file_details(file_id)
    if not rows: raise HTTPException(404,"لا توجد بيانات")
    data = []
    for r in rows:
        row = {"كود العميل":r["client_code"],"رقم الفاتورة":r["invoice_id"],
               "تاريخ الفاتورة":r["invoice_date"],"تسلسل":r["sort_value"],
               "المتبقي الأصلي":r["original_rem"],"المبلغ الموزع":r["distributed"],
               "المتبقي بعد التوزيع":r["remaining"],"الحالة":r["status"]}
        row.update(r.get("extra",{}))
        data.append(row)
    df=pd.DataFrame(data)
    out=UPLOAD_DIR/"history_export.xlsx"
    df.to_excel(out,index=False)
    return FileResponse(str(out),filename=f"{file['file_code']}.xlsx",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

# ── Diff API ───────────────────────────────────────────────────────────────────
@app.get("/api/diff/pairs")
async def diff_pairs(): return get_diff_pairs()

@app.get("/api/diff/details/{adil_id}/{sap_id}")
async def diff_details(adil_id:int, sap_id:int):
    return get_diff_details(adil_id,sap_id)

@app.post("/api/diff/complete")
async def diff_complete(data: dict):
    mark_diff_completed(data["file_code"],data["adil_id"],data["sap_id"],data.get("notes",""))
    return {"success":True}

@app.get("/api/diff/completed")
async def diff_completed_list(): return get_diff_completed()


@app.get("/ministries", response_class=HTMLResponse)
async def pg_ministries():
    return open(BASE_DIR/"static"/"ministries.html", encoding="utf-8").read()

@app.get("/api/ministries/export-csv")
async def export_ministries_csv():
    conn = local_conn()
    mins = conn.execute("SELECT id,[name] FROM ministries").fetchall()
    rows = []
    for m in mins:
        depts = conn.execute(
            "SELECT [name],[identifier] FROM departments WHERE ministry_id=?",
            (m["id"],)).fetchall()
        if depts:
            for d in depts:
                rows.append({"الوزارة":m["name"],"القسم":d["name"],"المعرف":d["identifier"]or""})
        else:
            rows.append({"الوزارة":m["name"],"القسم":"","المعرف":""})
    conn.close()
    import csv, io
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=["الوزارة","القسم","المعرف"])
    writer.writeheader()
    writer.writerows(rows)
    csv_content = "\ufeff" + output.getvalue()  # BOM for Arabic
    from fastapi.responses import Response
    return Response(
        content=csv_content.encode("utf-8-sig"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=ministries.csv"}
    )

@app.post("/api/ministries/preview-import")
async def preview_import_ministries(file: UploadFile = File(...)):
    """معاينة الاستيراد قبل التنفيذ"""
    ext = Path(file.filename).suffix.lower()
    tmp = UPLOAD_DIR / ("min_preview" + ext)
    tmp.write_bytes(await file.read())
    try:
        import pandas as pd
        df = pd.read_csv(tmp, encoding="utf-8-sig") if ext == ".csv" else pd.read_excel(tmp)
        # محاولة قراءة بترميز آخر
        if df.empty or df.columns[0].startswith("Unnamed"):
            if ext == ".csv":
                for enc in ["cp1256","utf-8","latin-1"]:
                    try:
                        df = pd.read_csv(tmp, encoding=enc)
                        if not df.empty: break
                    except: continue

        df.columns = [str(c).strip() for c in df.columns]

        # تحقق من الأعمدة
        col_map = {}
        for col in df.columns:
            cl = col.strip()
            if "وزار" in cl or cl.lower() in ["ministry","الوزارة"]:
                col_map["ministry"] = col
            elif "قسم" in cl or "dept" in cl.lower() or cl.lower() == "القسم":
                col_map["dept"] = col
            elif "معرف" in cl or "id" in cl.lower() or cl.lower() == "المعرف":
                col_map["identifier"] = col

        if "ministry" not in col_map:
            # محاولة بالترتيب
            cols = list(df.columns)
            if len(cols) >= 1: col_map["ministry"]   = cols[0]
            if len(cols) >= 2: col_map["dept"]        = cols[1]
            if len(cols) >= 3: col_map["identifier"]  = cols[2]

        if "ministry" not in col_map:
            raise HTTPException(400, "لم يتم العثور على عمود الوزارة في الملف")

        # تحميل البيانات الموجودة
        conn = local_conn()
        exist_mins = {r["name"]: r["id"] for r in
                      conn.execute("SELECT id,[name] FROM ministries").fetchall()}
        exist_depts = {}
        for mid in exist_mins.values():
            for r in conn.execute(
                "SELECT [name] FROM departments WHERE ministry_id=?", (mid,)).fetchall():
                exist_depts[(mid, r["name"])] = True
        conn.close()

        rows = []
        new_count = exist_count = 0
        for _, row in df.iterrows():
            min_name = str(row.get(col_map.get("ministry",""), "")).strip()
            dept_name = str(row.get(col_map.get("dept",""), "")).strip() if "dept" in col_map else ""
            ident = str(row.get(col_map.get("identifier",""), "")).strip() if "identifier" in col_map else ""
            if not min_name or min_name.lower() in ("nan","none",""): continue
            if ident.lower() in ("nan","none"): ident = ""
            if dept_name.lower() in ("nan","none"): dept_name = ""

            # هل موجود؟
            is_new = True
            if min_name in exist_mins:
                mid = exist_mins[min_name]
                if not dept_name or (mid, dept_name) in exist_depts:
                    is_new = False

            if is_new: new_count += 1
            else: exist_count += 1

            rows.append({
                "ministry":   min_name,
                "dept":       dept_name,
                "identifier": ident,
                "is_new":     is_new
            })

        return {
            "success":     True,
            "rows":        rows[:200],  # عرض أول 200 صف
            "total":       len(rows),
            "new_count":   new_count,
            "exist_count": exist_count
        }
    except HTTPException: raise
    except Exception as e:
        raise HTTPException(400, "خطأ في قراءة الملف: " + str(e))

# ── Backup ─────────────────────────────────────────────────────────────────────
@app.post("/api/backup")
async def do_backup():
    try:
        import shutil
        ts  = datetime.now().strftime("%Y%m%d_%H%M%S")
        out = UPLOAD_DIR/f"backup_{ts}.xlsx"
        rows= get_files_list()
        if not rows: return {"success":False,"message":"لا توجد بيانات للنسخ الاحتياطي"}
        all_data=[]
        for f in rows:
            dets=get_file_details(f["id"])
            for d in dets:
                r={"file_code":f["file_code"],"system":f["system_type"],"label":f["label"]}
                r.update(d); all_data.append(r)
        pd.DataFrame(all_data).to_excel(out,index=False)
        return FileResponse(str(out),filename=f"نسخة_احتياطية_{ts}.xlsx",
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    except Exception as e:
        raise HTTPException(500,str(e))

# ── Launch ─────────────────────────────────────────────────────────────────────
def open_browser():
    time.sleep(1.5)
    # لا يكفي وجود إعدادات محفوظة؛ يجب نجاح الاتصال فعلياً.
    cfg = get_sql_config()
    ready = bool(cfg and test_sql_connection(cfg).get("success"))
    webbrowser.open("http://localhost:8765/app" if ready else "http://localhost:8765/setup")

if __name__=="__main__":
    import socket as _socket
    with _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM) as _probe:
        _probe.settimeout(0.5)
        if _probe.connect_ex(("127.0.0.1", 8765)) == 0:
            print("\n[INFO] Adil System is already running at http://localhost:8765/app")
            webbrowser.open("http://localhost:8765/app")
            raise SystemExit(0)
    threading.Thread(target=open_browser,daemon=True).start()
    print("\n"+"="*55)
    print("  🔥 نظام العادل لتوزيع الأقساط v7")
    print("  🌐 http://localhost:8765")
    print("="*55+"\n")
    uvicorn.run(app,host="0.0.0.0",port=8765,log_level="warning")
