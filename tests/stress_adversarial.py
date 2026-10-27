# -*- coding: utf-8 -*-
"""v3.4 adversarial tests: tricky environments and edge cases."""
import json, os, shutil, sqlite3, sys, tempfile, threading, time

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


def env(bots=1, groups=1, logs=1, items=10, prefix="adv_"):
    root = tempfile.mkdtemp(prefix=prefix)
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


def a1_locked_db(rounds):
    print("=== A1 source db locked by another connection ===")
    for r in range(rounds):
        root, dd, br, pairs = env()
        p = pairs[0]
        br.upsert_sync_pair(p["old"], p["old_group"], p["current"], p["group"])
        holder = sqlite3.connect(br.logs_path, timeout=30)
        try:
            holder.execute("BEGIN EXCLUSIVE")
            holder.execute("SELECT COUNT(*) FROM logs").fetchone()
            done = []
            def w():
                try:
                    done.append(br.sync_all(only_due=False).get("ok"))
                except Exception as e:
                    done.append("exc:%r" % (e,))
            t = threading.Thread(target=w)
            t.start()
            time.sleep(0.4)
            try:
                holder.commit()
            except Exception:
                pass
            t.join(timeout=120)
            check(done and done[0] is True, "A1 r%d sync survived lock (%s)" % (r, done))
        finally:
            holder.close()
        shutil.rmtree(root, ignore_errors=True)


def a2_weird_names(rounds):
    print("=== A2 weird log titles ===")
    titles = ["a b", "a  (2)", "RTL" + "\u202e", "emoji \U0001F600", "quote[1] {x}",
              "\u4e2d\u6587\u540d", "tab\ttab", "dot.dot", "a/b\\\\c", "0" * 80]
    for r in range(rounds):
        root, dd, br, pairs = env(bots=1, groups=1, logs=len(titles), items=5)
        lg = os.path.join(dd, "data-logs.db")
        con = sqlite3.connect(lg)
        try:
            con.execute("DELETE FROM logs")
            con.execute("DELETE FROM log_items")
            for i, t in enumerate(titles):
                con.execute("INSERT INTO logs(name,group_id,created_at,updated_at,size,extra,upload_url,upload_time) VALUES(?,?,?,?,?,?,?,?)",
                            (t, "QQ-Group:60000", 1770000000 + i, 1770000000 + i, 0, "", None, None))
            con.commit()
        finally:
            con.close()
        p = pairs[0]
        br.upsert_sync_pair(p["old"], p["old_group"], p["current"], p["group"])
        res = br.sync_once(p)
        check(res.get("ok") is True, "A2 r%d sync ok" % r)
        con = sqlite3.connect(lg)
        try:
            n = con.execute("SELECT COUNT(*) FROM logs WHERE group_id=?", (p["group"],)).fetchone()[0]
            names = [x[0] for x in con.execute("SELECT name FROM logs WHERE group_id=?", (p["group"],)).fetchall()]
        finally:
            con.close()
        check(n == len(titles), "A2 r%d all %d titles copied (got %d)" % (r, len(titles), n))
        check(len(set(names)) == len(names), "A2 r%d names unique" % r)
        shutil.rmtree(root, ignore_errors=True)


def a3_gbk_text(rounds):
    print("=== A3 GBK-encoded text ===")
    for r in range(rounds):
        root, dd, br, pairs = env()
        raw = "\u6d4b\u8bd5GBK\u6587\u672c".encode("gb18030")
        lg = os.path.join(dd, "data-logs.db")
        con = sqlite3.connect(lg)
        try:
            con.text_factory = bytes
            con.execute("UPDATE logs SET name=? WHERE id=1", (raw,))
            con.commit()
        finally:
            con.close()
        p = pairs[0]
        br.upsert_sync_pair(p["old"], p["old_group"], p["current"], p["group"])
        try:
            res = br.sync_once(p)
            ok = res.get("ok") is True
        except Exception as e:
            ok = False
            print("   A3 r%d exc %r" % (r, e))
        check(ok, "A3 r%d gbk row handled" % r)
        shutil.rmtree(root, ignore_errors=True)


def a4_huge_log(rounds):
    print("=== A4 one huge log ===")
    for r in range(rounds):
        root, dd, br, pairs = env(logs=1, items=5000)
        p = pairs[0]
        br.upsert_sync_pair(p["old"], p["old_group"], p["current"], p["group"])
        br.sync_once(p)
        lp = os.path.join(dd, "data-logs.db")
        con = sqlite3.connect(lp)
        try:
            n = con.execute("SELECT COUNT(*) FROM log_items WHERE group_id=?", (p["group"],)).fetchone()[0]
        finally:
            con.close()
        check(n == 5000, "A4 r%d 5000 items (got %d)" % (r, n))
        shutil.rmtree(root, ignore_errors=True)


def a5_many_pairs(rounds):
    print("=== A5 many sync pairs ===")
    for r in range(rounds):
        root, dd, br, pairs = env(logs=1, items=5)
        for i in range(300):
            br.upsert_sync_pair(str(1000 + i), "1", "OpenQQ:P%d" % i, "OpenQQ-Group:Q%d" % i)
        res = br.sync_all(only_due=False)
        check(res.get("ok") is True and res.get("ran") == 300, "A5 r%d ran=%s" % (r, res.get("ran")))
        check(len(br.list_sync_pairs()) == 300, "A5 r%d pairs=300" % r)
        shutil.rmtree(root, ignore_errors=True)


def a6_missing_logs_db(rounds):
    print("=== A6 missing data-logs.db ===")
    for r in range(rounds):
        root, dd, br, pairs = env()
        p = pairs[0]
        br.upsert_sync_pair(p["old"], p["old_group"], p["current"], p["group"])
        os.remove(br.logs_path)
        try:
            res = br.sync_once(p)
            ok = res.get("ok") is True
        except Exception as e:
            ok = False
            print("   A6 r%d exc %r" % (r, e))
        check(ok, "A6 r%d sync handled missing logs db" % r)
        check(len(br.list_sync_pairs()) == 1, "A6 r%d pairs intact" % r)
        shutil.rmtree(root, ignore_errors=True)


def a7_corrupt_logs_db(rounds):
    print("=== A7 corrupt data-logs.db header ===")
    for r in range(rounds):
        root, dd, br, pairs = env()
        p = pairs[0]
        br.upsert_sync_pair(p["old"], p["old_group"], p["current"], p["group"])
        with open(br.logs_path, "r+b") as f:
            f.seek(20)
            f.write(b"\x00" * 40)
        try:
            res = br.sync_once(p)
            ok = isinstance(res, dict)
        except Exception as e:
            ok = False
            print("   A7 r%d exc %r" % (r, e))
        check(ok, "A7 r%d corrupt db did not explode" % r)
        check(len(br.list_sync_pairs()) == 1, "A7 r%d pairs intact" % r)
        shutil.rmtree(root, ignore_errors=True)


def a8_ms_timestamps(rounds):
    print("=== A8 millisecond timestamps ===")
    for r in range(rounds):
        root, dd, br, pairs = env()
        p = pairs[0]
        br.upsert_sync_pair(p["old"], p["old_group"], p["current"], p["group"])
        br.sync_once(p)
        con = sqlite3.connect(os.path.join(dd, "data.db"))
        try:
            con.execute("UPDATE attrs SET updated_at=updated_at*1000")
            con.commit()
        finally:
            con.close()
        res = br.sync_once(p)
        check(res.get("ok") is True, "A8 r%d sync with ms ts ok" % r)
        shutil.rmtree(root, ignore_errors=True)


def a9_two_bridge_instances(rounds):
    print("=== A9 two Bridge objects on same dir ===")
    for r in range(rounds):
        root, dd, br, pairs = env(groups=2, logs=1, items=5)
        br2 = B.Bridge(dd)
        br2.bindings_file = os.path.join(root, "bridge_bindings.json")
        br2.sync_config_file = os.path.join(root, "sync_config.json")
        errs = []
        def w(b, i):
            try:
                for k in range(5):
                    b.upsert_sync_pair(str(700 + i), "1", "OpenQQ:T%d-%d" % (i, k), "OpenQQ-Group:U%d-%d" % (i, k))
                    b.sync_all(only_due=False)
            except Exception as e:
                errs.append(repr(e))
        ths = [threading.Thread(target=w, args=(br, 1)), threading.Thread(target=w, args=(br2, 2))]
        for t in ths: t.start()
        for t in ths: t.join(timeout=300)
        check(not errs, "A9 r%d no errors (%s)" % (r, errs[:2]))
        try:
            cfg = json.load(open(br.sync_config_file, encoding="utf-8"))
            ok = isinstance(cfg.get("pairs"), list)
        except Exception:
            ok = False
        check(ok, "A9 r%d config json valid" % r)
        check(not [f for f in os.listdir(root) if f.endswith(".tmp")], "A9 r%d no tmp" % r)
        shutil.rmtree(root, ignore_errors=True)


def a10_rapid_pair_edit(rounds):
    print("=== A10 rapid add/remove pairs ===")
    for r in range(rounds):
        root, dd, br, pairs = env()
        errs = []
        def w(n):
            try:
                for k in range(20):
                    cur = "OpenQQ:R%d-%d" % (n, k)
                    grp = "OpenQQ-Group:S%d-%d" % (n, k)
                    br.upsert_sync_pair(str(800 + n), "1", cur, grp)
                    if k % 3 == 0:
                        br.remove_sync_pair(str(800 + n), "1", cur, grp)
                    br.load_sync_config()
            except Exception as e:
                errs.append(repr(e))
        ths = [threading.Thread(target=w, args=(i,)) for i in range(6)]
        for t in ths: t.start()
        for t in ths: t.join(timeout=300)
        check(not errs, "A10 r%d no errors (%s)" % (r, errs[:2]))
        check(not [f for f in os.listdir(root) if f.endswith(".tmp")], "A10 r%d no tmp" % r)
        shutil.rmtree(root, ignore_errors=True)


def a11_backup_prune(rounds):
    print("=== A11 first snapshot survives pruning ===")
    for r in range(rounds):
        root, dd, br, pairs = env(logs=1, items=5)
        p = pairs[0]
        br.upsert_sync_pair(p["old"], p["old_group"], p["current"], p["group"])
        for i in range(8):
            br._last_backup_at.clear()
            br.sync_once(p)
        firsts = [f for f in os.listdir(dd) if f.endswith(".snapshot-first.bak")]
        rolling = [f for f in os.listdir(dd) if ".before-sync-" in f]
        check(len(firsts) == 2, "A11 r%d 2 firsts (got %d)" % (r, len(firsts)))
        check(len(rolling) <= 4, "A11 r%d rolling <=4 (got %d)" % (r, len(rolling)))
        shutil.rmtree(root, ignore_errors=True)


def a12_zero_item_log(rounds):
    print("=== A12 empty logs ===")
    for r in range(rounds):
        root, dd, br, pairs = env(logs=2, items=0)
        p = pairs[0]
        br.upsert_sync_pair(p["old"], p["old_group"], p["current"], p["group"])
        res = br.sync_once(p)
        check(res.get("ok") is True, "A12 r%d sync empty logs ok" % r)
        con = sqlite3.connect(os.path.join(dd, "data-logs.db"))
        try:
            n = con.execute("SELECT COUNT(*) FROM logs WHERE group_id=?", (p["group"],)).fetchone()[0]
        finally:
            con.close()
        check(n == 2, "A12 r%d 2 empty logs copied (got %d)" % (r, n))
        shutil.rmtree(root, ignore_errors=True)


def a13_bind_during_long_sync(rounds):
    print("=== A13 bind during slow sync ===")
    for r in range(rounds):
        root, dd, br, pairs = env(bots=2, groups=3, logs=2, items=40)
        for p in pairs:
            br.upsert_sync_pair(p["old"], p["old_group"], p["current"], p["group"])
        orig = br.sync_once
        def slow(pair):
            time.sleep(0.2)
            return orig(pair)
        br.sync_once = slow
        added = []
        errs = []
        def binder(n):
            try:
                time.sleep(0.05 * n)
                q = br.upsert_sync_pair(str(900 + n), "9", "OpenQQ:V%d" % n, "OpenQQ-Group:W%d" % n)
                added.append(br.sync_pair_key(q["old"], q["old_group"], q["current"], q["group"]))
            except Exception as e:
                errs.append(repr(e))
        t = threading.Thread(target=lambda: br.sync_all(only_due=False))
        bs = [threading.Thread(target=binder, args=(i,)) for i in range(1, 6)]
        t.start()
        for b in bs: b.start()
        t.join(timeout=600)
        for b in bs: b.join(timeout=300)
        br.sync_once = orig
        keys = set()
        for p in br.list_sync_pairs():
            keys.add(br.sync_pair_key(p["old"], p["old_group"], p["current"], p["group"]))
        missing = [k for k in added if k not in keys]
        check(not errs, "A13 r%d no errors (%s)" % (r, errs[:2]))
        check(not missing, "A13 r%d binds survived (%d missing)" % (r, len(missing)))
        shutil.rmtree(root, ignore_errors=True)


def a14_special_group_ids(rounds):
    print("=== A14 unusual group identifiers ===")
    for r in range(rounds):
        root, dd, br, pairs = env(logs=1, items=5)
        ids = ["OpenQQ-Group:401-XYZ-abcdef", "QQ-Group:1", "OpenQQ-Group:x", "OpenQQ-Group:" + "z" * 120]
        for i, gid in enumerate(ids):
            br.upsert_sync_pair(str(600 + i), "1", "OpenQQ:U%d" % i, gid)
        res = br.sync_all(only_due=False)
        check(res.get("ok") is True and res.get("ran") == len(ids), "A14 r%d ran=%s" % (r, res.get("ran")))
        shutil.rmtree(root, ignore_errors=True)


def a15_reload_plugin_keeps_pairs(rounds):
    print("=== A15 restart bridge keeps bindings ===")
    for r in range(rounds):
        root, dd, br, pairs = env(bots=2, groups=2, logs=1, items=5)
        for p in pairs:
            br.upsert_sync_pair(p["old"], p["old_group"], p["current"], p["group"])
        before = len(br.list_sync_pairs())
        br2 = B.Bridge(dd)
        br2.bindings_file = br.bindings_file
        br2.sync_config_file = br.sync_config_file
        after = len(br2.list_sync_pairs())
        check(before == after == len(pairs), "A15 r%d pairs survive restart (%d/%d)" % (r, before, after))
        res = br2.sync_all(only_due=False)
        check(res.get("ok") is True, "A15 r%d new instance can sync" % r)
        shutil.rmtree(root, ignore_errors=True)


def a16_disk_full_simulation(rounds):
    print("=== A16 backup failure is tolerated ===")
    for r in range(rounds):
        root, dd, br, pairs = env(logs=1, items=5)
        p = pairs[0]
        br.upsert_sync_pair(p["old"], p["old_group"], p["current"], p["group"])
        br._snapshot_sqlite_orig = br._snapshot_sqlite
        def boom(src, dst):
            raise OSError(28, "No space left on device")
        br._snapshot_sqlite = boom
        res = br.sync_once(p)
        check(res.get("ok") is True, "A16 r%d sync ok despite backup failure" % r)
        br._snapshot_sqlite = br._snapshot_sqlite_orig
        check(len(br.list_sync_pairs()) == 1, "A16 r%d pairs intact" % r)
        shutil.rmtree(root, ignore_errors=True)


def main():
    total = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    print("v3.4 adversarial tests: %d rounds each scenario" % total)
    t0 = time.time()
    a1_locked_db(total)
    a2_weird_names(total)
    a3_gbk_text(total)
    a4_huge_log(max(5, total // 4))
    a5_many_pairs(max(5, total // 4))
    a6_missing_logs_db(total)
    a7_corrupt_logs_db(total)
    a8_ms_timestamps(total)
    a9_two_bridge_instances(max(10, total // 2))
    a10_rapid_pair_edit(max(10, total // 2))
    a11_backup_prune(total)
    a12_zero_item_log(total)
    a13_bind_during_long_sync(max(10, total // 2))
    a14_special_group_ids(total)
    a15_reload_plugin_keeps_pairs(total)
    a16_disk_full_simulation(total)
    print()
    print("=" * 60)
    print("checks=%d failures=%d elapsed=%.1fs" % (CHECKS[0], len(FAILS), time.time() - t0))
    if FAILS:
        print("FAILED (%d):" % len(FAILS))
        for f in FAILS[:30]:
            print("  " + f)
        sys.exit(1)
    print("ALL ADVERSARIAL TESTS PASSED")


if __name__ == "__main__":
    main()
