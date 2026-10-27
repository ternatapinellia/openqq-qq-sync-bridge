# -*- coding: utf-8 -*-
import json, os, random, shutil, sqlite3, sys, tempfile, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "docker"))
sys.path.insert(0, HERE)

import bridge as B
from seadice_fixture import make_data_db, make_logs_db

FAILS = []
CHECKS = [0]


def check(cond, label):
    CHECKS[0] += 1
    if not cond:
        FAILS.append(label)
        print("  FAIL " + label)


def new_env(bots=3, groups=4, logs=2, items=30):
    root = tempfile.mkdtemp(prefix="stress_")
    os.environ["OPENQQ_BRIDGE_ROOT"] = root
    dd = os.path.join(root, "data")
    os.makedirs(dd, exist_ok=True)
    make_data_db(os.path.join(dd, "data.db"), with_cards=True)
    lg = []
    pairs = []
    for b in range(bots):
        q = str(50000 + b)
        for g in range(groups):
            gid = "QQ-Group:%d" % (60000 + b * 100 + g)
            for k in range(logs):
                lg.append({"name": "L%d-%d-%d" % (b, g, k), "group_id": gid,
                           "created_at": 1770000000 + b * 1000 + g * 10 + k,
                           "items": ["m%d" % i for i in range(items)]})
            pairs.append({"old": q, "old_group": gid,
                          "current": "OpenQQ:401-B%d-%d" % (b, g),
                          "group": "OpenQQ-Group:401-A%d-%d" % (b, g)})
    make_logs_db(os.path.join(dd, "data-logs.db"), lg)
    br = B.Bridge(dd)
    br.bindings_file = os.path.join(root, "bridge_bindings.json")
    br.sync_config_file = os.path.join(root, "sync_config.json")
    return root, dd, br, pairs


def count_items(logs_path, gid):
    con = sqlite3.connect(logs_path)
    try:
        return int(con.execute("SELECT COUNT(*) FROM log_items WHERE group_id=?", (gid,)).fetchone()[0] or 0)
    finally:
        con.close()


def s1(rounds):
    print("=== S1 concurrent mix ===")
    for r in range(rounds):
        root, dd, br, pairs = new_env()
        for p in pairs:
            br.upsert_sync_pair(p["old"], p["old_group"], p["current"], p["group"])
        errs = []
        def sw():
            try: br.sync_all(only_due=False)
            except Exception as e: errs.append(repr(e))
        def bw(n):
            try: br.upsert_sync_pair(str(90000+n), "700", "OpenQQ:401-Z%d" % n, "OpenQQ-Group:401-Z%d" % n)
            except Exception as e: errs.append(repr(e))
        def cw():
            try: br.load_sync_config()
            except Exception as e: errs.append(repr(e))
        ths = [threading.Thread(target=sw) for _ in range(3)]
        ths += [threading.Thread(target=bw, args=(i,)) for i in range(6)]
        ths += [threading.Thread(target=cw) for _ in range(2)]
        for t in ths: t.start()
        for t in ths: t.join(timeout=300)
        check(not errs, "S1 r%d errors=%s" % (r, errs[:2]))
        check(len(br.list_sync_pairs()) >= len(pairs)+6, "S1 r%d pairs" % r)
        check(not [f for f in os.listdir(root) if f.endswith(".tmp")], "S1 r%d tmp" % r)
        shutil.rmtree(root, ignore_errors=True)


def s2(rounds):
    print("=== S2 idempotency ===")
    for r in range(rounds):
        root, dd, br, pairs = new_env(bots=1, groups=1, logs=3, items=20)
        p = pairs[0]
        for _ in range(4): br.sync_once(p)
        lp = os.path.join(dd, "data-logs.db")
        con = sqlite3.connect(lp)
        try:
            nl = con.execute("SELECT COUNT(*) FROM logs WHERE group_id=?", (p["group"],)).fetchone()[0]
            ni = con.execute("SELECT COUNT(*) FROM log_items WHERE group_id=?", (p["group"],)).fetchone()[0]
        finally: con.close()
        check(nl == 3, "S2 r%d logs=%d" % (r, nl))
        check(ni == 60, "S2 r%d items=%d" % (r, ni))
        shutil.rmtree(root, ignore_errors=True)


def s3(rounds):
    print("=== S3 backup throttle ===")
    for r in range(rounds):
        root, dd, br, pairs = new_env(bots=2, groups=3, logs=1, items=10)
        for p in pairs: br.upsert_sync_pair(p["old"], p["old_group"], p["current"], p["group"])
        for _ in range(6): br.sync_all(only_due=False)
        baks = [f for f in os.listdir(dd) if ".before-sync-" in f]
        firsts = [f for f in os.listdir(dd) if f.endswith(".snapshot-first.bak")]
        check(len(firsts) == 2, "S3 r%d firsts=%d" % (r, len(firsts)))
        check(len(baks) <= 4, "S3 r%d baks=%d" % (r, len(baks)))
        shutil.rmtree(root, ignore_errors=True)


def s4(rounds):
    print("=== S4 bidirectional append ===")
    for r in range(rounds):
        root, dd, br, pairs = new_env(bots=1, groups=1, logs=1, items=10)
        p = pairs[0]
        br.sync_once(p)
        lp = os.path.join(dd, "data-logs.db")
        con = sqlite3.connect(lp)
        try:
            lid = con.execute("SELECT id FROM logs WHERE group_id=? LIMIT 1", (p["group"],)).fetchone()[0]
            nid = con.execute("SELECT COALESCE(MAX(id),0) FROM log_items").fetchone()[0]+1
            con.execute("INSERT INTO log_items(id,log_id,group_id,nickname,im_userid,time,message,is_dice,command_id,command_info,raw_msg_id,user_uniform_id,removed,parent_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (nid, lid, p["group"], "x", "QQ:1", 1, "extra", 0, 0, "", "r", "u", 0, None))
            con.commit()
        finally: con.close()
        br.sync_once(p)
        got = count_items(lp, p["group"])
        check(got >= 11, "S4 r%d items=%d" % (r, got))
        shutil.rmtree(root, ignore_errors=True)


def s5(rounds):
    print("=== S5 http concurrency ===")
    import urllib.request
    from http.server import ThreadingHTTPServer
    for r in range(rounds):
        root, dd, br, pairs = new_env(bots=1, groups=1, logs=1, items=5)
        br.upsert_sync_pair(pairs[0]["old"], pairs[0]["old_group"], pairs[0]["current"], pairs[0]["group"])
        B.Handler.bridge = br
        B.Handler.token = ""
        srv = ThreadingHTTPServer(("127.0.0.1", 0), B.Handler)
        port = srv.server_address[1]
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        errs = []
        def hit(path):
            try: urllib.request.urlopen("http://127.0.0.1:%d%s" % (port, path), timeout=15).read()
            except Exception as e: errs.append("%s %r" % (path, e))
        ths = [threading.Thread(target=hit, args=("/health",)) for _ in range(5)]
        ths += [threading.Thread(target=hit, args=("/sync-status",)) for _ in range(5)]
        ths += [threading.Thread(target=hit, args=("/sync-now",)) for _ in range(3)]
        for x in ths: x.start()
        for x in ths: x.join(timeout=180)
        srv.shutdown()
        check(not errs, "S5 r%d errs=%s" % (r, errs[:2]))
        shutil.rmtree(root, ignore_errors=True)


def s6(rounds):
    print("=== S6 large scale ===")
    for r in range(rounds):
        root, dd, br, pairs = new_env(bots=6, groups=6, logs=3, items=40)
        for p in pairs: br.upsert_sync_pair(p["old"], p["old_group"], p["current"], p["group"])
        errs = []
        def w():
            try: br.sync_all(only_due=False)
            except Exception as e: errs.append(repr(e))
        ths = [threading.Thread(target=w) for _ in range(4)]
        for x in ths: x.start()
        for x in ths: x.join(timeout=900)
        check(not errs, "S6 r%d errs=%s" % (r, errs[:2]))
        check(len(br.list_sync_pairs()) == len(pairs), "S6 r%d pairs=%d" % (r, len(br.list_sync_pairs())))
        shutil.rmtree(root, ignore_errors=True)


def s7(rounds):
    print("=== S7 bad input ===")
    for r in range(rounds):
        root, dd, br, pairs = new_env(bots=1, groups=1, logs=1, items=5)
        with open(br.sync_config_file, "w", encoding="utf-8") as f: f.write("{ bad json")
        try: ok1 = isinstance(br.load_sync_config(), dict)
        except Exception: ok1 = False
        check(ok1, "S7 r%d corrupt tolerated" % r)
        try:
            br.upsert_sync_pair("1","2","OpenQQ:X","OpenQQ-Group:Y"); ok2 = True
        except Exception: ok2 = False
        check(ok2, "S7 r%d write after corrupt" % r)
        try: ok3 = br.sync_all(only_due=False).get("ok") is True
        except Exception: ok3 = False
        check(ok3, "S7 r%d sync survives" % r)
        shutil.rmtree(root, ignore_errors=True)


def main():
    total = int(sys.argv[1]) if len(sys.argv) > 1 else 100
    print("v3.4 comprehensive stress: %d rounds" % total)
    t0 = time.time()
    s1(total); s2(total); s3(total); s4(total)
    s5(max(10, total//5)); s6(max(10, total//5)); s7(total)
    print()
    print("=" * 60)
    print("checks=%d failures=%d elapsed=%.1fs" % (CHECKS[0], len(FAILS), time.time()-t0))
    if FAILS:
        for f in FAILS[:20]: print("  " + f)
        sys.exit(1)
    print("ALL COMPREHENSIVE STRESS TESTS PASSED")


if __name__ == "__main__":
    main()