===============================================
نظام العادل لتوزيع الأقساط v7 - دليل التثبيت
===============================================

المتطلبات:
----------
- Python 3.8+ (على كل الأجهزة)
- SQL Server Express (على جهاز السيرفر فقط)
- ODBC Driver 17 or 18 for SQL Server (على كل الأجهزة)

خطوات التثبيت:
--------------

على جهاز السيرفر:
1. تثبيت SQL Server Express:
   https://www.microsoft.com/en-us/sql-server/sql-server-downloads
   (اختر Express - مجاني)

2. تشغيل setup_sqlserver.bat

3. تفعيل TCP/IP في SQL Server Configuration Manager:
   - ابحث عن "SQL Server Configuration Manager" في قائمة ابدأ
   - SQL Server Network Configuration
   - Protocols for SQLEXPRESS
   - TCP/IP -> Enable
   - أعد تشغيل SQL Server Service

على كل جهاز عميل:
1. تثبيت ODBC Driver 17:
   https://aka.ms/downloadmsodbcsql
   
2. تشغيل install_requirements.bat

3. تشغيل install_and_run.py

4. عند أول تشغيل، ستظهر صفحة إعداد الاتصال
   أدخل: Server Name, Database, Username, Password

ملاحظات:
---------
- قاعدة البيانات تدعم 20+ مستخدم متزامن
- جميع البيانات تُحفظ مركزياً في SQL Server
- الإعدادات المحلية (SQLite) تُحفظ على كل جهاز
- لا حاجة لتثبيت SSMS على أجهزة العملاء

للدعم الفني: تواصل مع مطور النظام
===============================================
