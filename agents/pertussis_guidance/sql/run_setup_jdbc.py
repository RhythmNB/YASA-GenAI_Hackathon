"""Run every statement of setup.sql through plain JDBC Statements
(no bind-parameter parsing), skipping ones that already exist and printing the
rows of the SELECT checks."""
import os, re
from pathlib import Path

ENV = Path(r"F:\Hackathon\getting-started\.env.local")
for line in ENV.read_text(encoding="utf-8").splitlines():
    if "=" in line and not line.startswith("#"):
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())
os.environ["JAVA_HOME"] = r"F:\jdk-23.0.2"

text = Path(r"F:\Hackathon\YASA-GenAI_Hackathon\visit-planner-handoff\sql\setup.sql").read_text(encoding="utf-8")
def body(s):
    return "\n".join(l for l in s.splitlines() if not l.lstrip().startswith("--")).strip()
stmts = [body(s) for s in re.split(r";\s*\n", text) if body(s)]

import jaydebeapi
conn = jaydebeapi.connect("com.zetaris.lightning.jdbc.LightningDriver", os.environ["ZETARIS_JDBC_URL"],
                          [os.environ["ZETARIS_USERNAME"], os.environ["ZETARIS_PASSWORD"]], os.environ["ZETARIS_JDBC_JAR"])
ok = skipped = failed = 0
for i, sql in enumerate(stmts, 1):
    head = " ".join(sql.split())[:80]
    st = conn.jconn.createStatement()
    try:
        has_rs = st.execute(sql)
        if has_rs:
            rs = st.getResultSet(); md = rs.getMetaData(); n = md.getColumnCount()
            cols = [str(md.getColumnLabel(c)) for c in range(1, n + 1)]
            rows = []
            while rs.next() and len(rows) < 60:
                rows.append([None if rs.getObject(c) is None else str(rs.getObject(c)) for c in range(1, n + 1)])
            print(f"{i:2}. {head}\n    {len(rows)} rows: {cols}")
            for r in rows[:12]:
                print("    ", r)
            if len(rows) > 12:
                print("     ...")
        else:
            print(f"{i:2}. {head}\n    ok")
        ok += 1
    except Exception as e:  # noqa: BLE001
        msg = str(e)
        if "exist" in msg.lower():
            print(f"{i:2}. {head}\n    skipped (already exists)"); skipped += 1
        else:
            print(f"{i:2}. {head}\n    ERROR {msg[:400]}"); failed += 1
    finally:
        st.close()
conn.close()
print(f"done: ok={ok} skipped={skipped} failed={failed}")
