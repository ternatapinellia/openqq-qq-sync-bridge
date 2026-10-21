# -*- coding: utf-8 -*-
"""OpenQQ QQ Sync Bridge —— 回归测试。

直接跑： python tests/test_bridge.py
不需要任何第三方库，也不需要真实的 SeaDice 数据。

覆盖：
  1. 备份策略（首份永久快照 + 最近 N 份滚动，两个库各自独立）
  2. 无角色卡放行 / 两边都空才拒绝
  3. log 撞名自动改名，不再整批回滚
  4. 逐条 log 独立提交：单条失败不影响其余
  5. 重复执行幂等：不重复搬运
  6. log_items 的 parent_id 重映射
  7. HTTP 层：/health、令牌校验、GET/POST 路由
  8. OpenAI... 不，是 root_dir() 的 OPENQQ_BRIDGE_ROOT 覆盖
"""
import io, json, os, shutil, sqlite3, sys, tempfile, threading, time, urllib.error, urllib.request
from http.server import ThreadingHTTPServer
from importlib.machinery import SourceFileLoader
from importlib.util import spec_from_loader, module_from_spec

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from seadice_fixture import make_data_db, make_logs_db, CARD_BLOB  # noqa: E402

FAILURES = []
CHECKS = [0]


def load_bridge(path=None):
    path = path or os.path.join(ROOT, "src", "bridge.py")
    name = "bridge_under_test_%d" % (abs(hash(path)) % 1000000)
    loader = SourceFileLoader(name, path)
    mod = module_from_spec(spec_from_loader(name, loader))
    sys.modules[name] = mod
    loader.exec_module(mod)
    return mod


def check(cond, label, detail=""):
    CHECKS[0] += 1
    if cond:
        print("  PASS  %s" % label)
    else:
        print("  FAIL  %s   %s" % (label, detail))
        FAILURES.append(label)


def section(title):
    print("\n=== %s ===" % title)


OLD_GROUP = "QQ-Group:1081354778"
TGT_GROUP = "OpenQQ-Group:4019039592-D3B44D0DFEC6A0EDF40AE7D10DA61273"
OLD_QQ = "1721175359"


def build_workspace(tmp, tag, target_logs=None, with_cards=True):
    w = os.path.join(tmp, tag)
    os.makedirs(w, exist_ok=True)
    mod = load_bridge()
    make_data_db(os.path.join(w, "data.db"), with_cards=with_cards)
    make_logs_db(os.path.join(w, "data-logs.db"), target_logs or [])
    return w, mod


def copy_db(src, dst):
    s = sqlite3.connect("file:%s?mode=ro" % src.replace("\\", "/"), uri=True)
    d = sqlite3.connect(dst)
    s.backup(d)
    d.close()
    s.close()


# ---------------------------------------------------------------- 1. 备份策略
section("1. backup policy")
tmp = tempfile.mkdtemp(prefix="bridge_test_")
try:
    w, mod = build_workspace(tmp, "bak")
    b = mod.Bridge(w)
    for i in range(5):
        b.backup_db_before_bind(label="r%d" % i)
        b.backup_logs_before_bind(label="r%d" % i)
        time.sleep(1.02)
    first_db = b.db_path + mod.BACKUP_FIRST_SUFFIX
    first_logs = b.logs_path + mod.BACKUP_FIRST_SUFFIX
    roll_db = [f for f in os.listdir(w) if f.startswith("data.db.before-sync-") and f.endswith(".bak")]
    roll_logs = [f for f in os.listdir(w) if f.startswith("data-logs.db.before-sync-") and f.endswith(".bak")]
    check(os.path.exists(first_db), "data.db keeps a permanent first snapshot")
    check(os.path.exists(first_logs), "data-logs.db keeps a permanent first snapshot")
    check(len(roll_db) == mod.BACKUP_KEEP_ROLLING, "data.db rolling backups pruned to %d" % mod.BACKUP_KEEP_ROLLING, "got %d %s" % (len(roll_db), roll_db))
    check(len(roll_logs) == mod.BACKUP_KEEP_ROLLING, "data-logs.db rolling backups pruned independently", "got %d %s" % (len(roll_logs), roll_logs))
    # first snapshot must never be overwritten even after many runs
    size_before = os.path.getsize(first_db)
    check(size_before > 0, "first snapshot is non-empty")
    # backups must be readable snapshots
    con = sqlite3.connect(first_db)
    n = con.execute("SELECT COUNT(*) FROM attrs").fetchone()[0]
    con.close()
    check(n == 3, "first snapshot is a valid readable sqlite db", "attrs=%d" % n)

    # -------------------------------------------------- 2. 无角色卡放行 / 双空拒绝
    section("2. request-code gate")
    w, mod = build_workspace(tmp, "gate")
    b = mod.Bridge(w)
    sent = []
    b.send_verification_email = lambda *a, **k: sent.append(a)

    from seadice_fixture import make_logs_db as _mk
    con = sqlite3.connect(b.logs_path)
    con.execute("INSERT INTO logs(name,group_id,created_at,updated_at,size,extra,upload_url,upload_time) VALUES(?,?,?,?,?,?,?,?)",
                ("某场记录", OLD_GROUP, 1770000111, 1770000111, 0, "", None, None))
    con.commit(); con.close()

    # 有 log、无角色卡 -> 放行
    try:
        r = b.request_code("999999999", OLD_GROUP.replace("QQ-Group:", ""), "OpenQQ:u", TGT_GROUP)
        check(r.get("ok") is True, "no card + has logs -> allowed", str(r))
    except Exception as e:
        check(False, "no card + has logs -> allowed", "%s: %s" % (type(e).__name__, e))
    # 有角色卡、无 log -> 放行
    try:
        r = b.request_code(OLD_QQ, "123456789", "OpenQQ:u", TGT_GROUP)
        check(r.get("ok") is True, "has cards + no logs -> allowed", str(r))
    except Exception as e:
        check(False, "has cards + no logs -> allowed", "%s: %s" % (type(e).__name__, e))
    # 两边都空 -> 拒绝
    try:
        b.request_code("999999999", "123456789", "OpenQQ:u", TGT_GROUP)
        check(False, "no card + no logs -> rejected", "expected RuntimeError")
    except RuntimeError as e:
        check("没有找到可迁移的数据" in str(e), "no card + no logs -> rejected", str(e))
    check(len(sent) == 2, "verification mail sent exactly twice", "sent=%d" % len(sent))

    # -------------------------------------------------- 3. 撞名自动改名
    section("3. duplicate log names")
    target = [
        dict(name="4时44分的火车站", group_id=TGT_GROUP, created_at=0, items=["目标已有1", "目标已有2"]),
        dict(name="行车不规范，亲人两行泪", group_id=TGT_GROUP, created_at=1789387361, items=["x"]),
    ]
    src = [
        dict(name="4时44分的火车站", group_id=OLD_GROUP, created_at=1770984083, items=["源A", "源B", "源C"]),
        dict(name="半夜打工也是工", group_id=OLD_GROUP, created_at=1771329822, items=["源D"]),
    ]
    w, mod = build_workspace(tmp, "dup", target_logs=target + src)
    b = mod.Bridge(w)
    r = b.migrate_logs(OLD_GROUP, TGT_GROUP)
    check(r["log_failed"] == 0, "no failures when a name collides", json.dumps(r, ensure_ascii=False))
    con = sqlite3.connect(b.logs_path); con.row_factory = sqlite3.Row
    names = [row["name"] for row in con.execute("SELECT name FROM logs WHERE group_id=? ORDER BY id", (TGT_GROUP,))]
    con.close()
    check("4时44分的火车站 (2)" in names, "colliding log renamed with (2) suffix", str(names))
    check(names.count("4时44分的火车站") == 1, "original target log left untouched", str(names))

    # -------------------------------------------------- 4. 单条失败隔离
    section("4. per-log failure isolation")
    src = [dict(name="好记录一", group_id=OLD_GROUP, created_at=1770000001, items=["a", "b"]),
           dict(name="坏记录", group_id=OLD_GROUP, created_at=1770000002, items=["c"]),
           dict(name="好记录二", group_id=OLD_GROUP, created_at=1770000003, items=["d", "e", "f"])]
    w, mod = build_workspace(tmp, "iso", target_logs=src)
    b = mod.Bridge(w)
    con = sqlite3.connect(b.logs_path)
    con.execute("""CREATE TRIGGER poison BEFORE INSERT ON logs
        WHEN NEW.group_id = '%s' AND NEW.name = '坏记录'
        BEGIN SELECT RAISE(ABORT, 'poisoned for test'); END;""" % TGT_GROUP)
    con.commit(); con.close()
    r = b.migrate_logs(OLD_GROUP, TGT_GROUP)
    check(r["log_count"] == 2, "2 of 3 logs migrated", json.dumps(r, ensure_ascii=False))
    check(r["log_failed"] == 1, "exactly 1 log reported as failed", json.dumps(r, ensure_ascii=False))
    check(any("坏记录" in e for e in r["log_errors"]), "failing log is named in log_errors", str(r["log_errors"]))
    con = sqlite3.connect(b.logs_path)
    got = [row[0] for row in con.execute("SELECT name FROM logs WHERE group_id=?", (TGT_GROUP,))]
    con.close()
    check(sorted(got) == ["好记录一", "好记录二"], "the two good logs truly landed", str(got))
    err_log = os.path.join(w, "bridge_error.log")
    check(os.path.exists(err_log) and "坏记录" in io.open(err_log, encoding="utf-8").read(),
          "bridge_error.log records the reason")

    # -------------------------------------------------- 5. 幂等
    section("5. idempotency")
    src = [dict(name="甲", group_id=OLD_GROUP, created_at=111, items=["1", "2"]),
           dict(name="乙", group_id=OLD_GROUP, created_at=222, items=["3"])]
    w, mod = build_workspace(tmp, "idem", target_logs=src)
    b = mod.Bridge(w)
    r1 = b.migrate_logs(OLD_GROUP, TGT_GROUP)
    r2 = b.migrate_logs(OLD_GROUP, TGT_GROUP)
    r3 = b.migrate_logs(OLD_GROUP, TGT_GROUP)
    check(r1["log_count"] == 2, "first run copies both logs", json.dumps(r1, ensure_ascii=False))
    check(r2["log_count"] == 0 and r2["log_skipped"] == 2, "second run copies nothing (recognised as migrated)", json.dumps(r2, ensure_ascii=False))
    check(r3["log_count"] == 0 and r3["log_skipped"] == 2, "third run also copies nothing", json.dumps(r3, ensure_ascii=False))
    con = sqlite3.connect(b.logs_path)
    total = con.execute("SELECT COUNT(*) FROM logs WHERE group_id=?", (TGT_GROUP,)).fetchone()[0]
    con.close()
    check(total == 2, "no duplicate rows accumulated", "rows=%d" % total)

    # idempotency must also hold when the first run had to rename (suffix path)
    src = [dict(name="撞名甲", group_id=OLD_GROUP, created_at=333, items=["1"]),
           dict(name="撞名甲", group_id=TGT_GROUP, created_at=333, items=["2", "3"])]
    w, mod = build_workspace(tmp, "idem2", target_logs=src)
    b = mod.Bridge(w)
    r1 = b.migrate_logs(OLD_GROUP, TGT_GROUP)
    r2 = b.migrate_logs(OLD_GROUP, TGT_GROUP)
    check(r1["log_count"] == 1 and r1["log_skipped"] == 0, "rename case: run1 copies", json.dumps(r1, ensure_ascii=False))
    check(r2["log_count"] == 0 and r2["log_skipped"] == 1, "rename case: run2 recognised the renamed copy", json.dumps(r2, ensure_ascii=False))

    # -------------------------------------------------- 6. parent_id 重映射
    section("6. parent_id remapping")
    src = [dict(name="带引用", group_id=OLD_GROUP, created_at=444,
                items=[("第一条", None), ("回复第一条", 0), ("再回复第一条", 0)])]
    w, mod = build_workspace(tmp, "parent", target_logs=src)
    b = mod.Bridge(w)
    b.migrate_logs(OLD_GROUP, TGT_GROUP)
    con = sqlite3.connect(b.logs_path); con.row_factory = sqlite3.Row
    rows = list(con.execute("SELECT id, message, parent_id FROM log_items WHERE group_id=? ORDER BY id", (TGT_GROUP,)))
    con.close()
    check(len(rows) == 3, "all 3 items copied", "n=%d" % len(rows))
    first_id = rows[0]["id"]
    check(rows[1]["parent_id"] == first_id, "child 1 points at the FIRST COPY of parent, not the source id",
          "parent_id=%s first_id=%s" % (rows[1]["parent_id"], first_id))
    check(rows[2]["parent_id"] == first_id, "child 2 points at the first copy too")

    # -------------------------------------------------- 7. HTTP 层
    section("7. HTTP layer")
    w, mod = build_workspace(tmp, "http")
    b = mod.Bridge(w)
    mod.Handler.bridge = b
    mod.Handler.token = ""
    port = 39123
    srv = ThreadingHTTPServer(("127.0.0.1", port), mod.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    time.sleep(0.25)

    def get(path, expect_ok=True):
        try:
            with urllib.request.urlopen("http://127.0.0.1:%d%s" % (port, path), timeout=5) as r:
                return r.status, r.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8")

    st, body = get("/health")
    check(st == 200 and json.loads(body).get("ok") is True, "/health works without a token", "%s %s" % (st, body))
    st, body = get("/lookup?old=1721175359")
    check(st == 200 and json.loads(body).get("character_count") == 3, "/lookup returns the 3 cards", "%s %s" % (st, body))
    st, body = get("/nope")
    check(st == 404, "unknown route -> 404", "%s %s" % (st, body))

    # now turn the token on
    mod.Handler.token = "s3cr3t"
    st, body = get("/lookup?old=1721175359")
    check(st == 401, "token on: request without token -> 401", "%s %s" % (st, body))
    st, body = get("/lookup?old=1721175359&token=wrong")
    check(st == 401, "token on: wrong token -> 401", "%s %s" % (st, body))
    st, body = get("/lookup?old=1721175359&token=s3cr3t")
    check(st == 200 and json.loads(body).get("character_count") == 3, "token on: correct token -> 200", "%s %s" % (st, body))
    st, body = get("/health")
    check(st == 200, "token on: /health still open (for container healthcheck)", "%s %s" % (st, body))
    srv.shutdown()

    # -------------------------------------------------- 8. root_dir override
    section("8. root_dir override")
    mod = load_bridge()
    old_env = os.environ.get("OPENQQ_BRIDGE_ROOT")
    try:
        os.environ["OPENQQ_BRIDGE_ROOT"] = tmp
        check(mod.root_dir() == os.path.abspath(tmp), "OPENQQ_BRIDGE_ROOT overrides config root", mod.root_dir())
    finally:
        if old_env is None:
            os.environ.pop("OPENQQ_BRIDGE_ROOT", None)
        else:
            os.environ["OPENQQ_BRIDGE_ROOT"] = old_env
    check(os.path.isabs(mod.root_dir()), "root_dir() is always absolute", mod.root_dir())
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("\n" + "=" * 56)
print("checks: %d   failures: %d" % (CHECKS[0], len(FAILURES)))
if FAILURES:
    for f in FAILURES:
        print("  - %s" % f)
    sys.exit(1)
print("ALL TESTS PASSED")
