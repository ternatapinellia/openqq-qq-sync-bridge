# -*- coding: utf-8 -*-
"""多官bot并发回归测试。

场景：一个海豹实例同时挂多个官方QQ机器人（多个群、多条同步关系），
用户在不同群里几乎同时完成绑定（写 sync_config.json），
而后台 SyncWorker 正在跑增量同步（也写 sync_config.json）。

重点验证 sync_all 的「读-改-写」不会把并发新增的同步关系覆盖丢失。
"""
import os, sys, tempfile, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "docker"))

import bridge as B  # noqa: E402

FAILS = []
CHECKS = [0]


def check(cond, label):
    CHECKS[0] += 1
    print(("  PASS  " if cond else "  FAIL  ") + label)
    if not cond:
        FAILS.append(label)


def fresh_bridge():
    tmp = tempfile.mkdtemp(prefix="bridge_multibot_")
    os.environ["OPENQQ_BRIDGE_ROOT"] = tmp
    br = B.Bridge(tmp)
    br.bindings_file = os.path.join(tmp, "bridge_bindings.json")
    br.sync_config_file = os.path.join(tmp, "sync_config.json")
    return br, tmp


print("=== 1. sync_all must not drop pairs added concurrently ===")
br, tmp = fresh_bridge()
br.upsert_sync_pair("111", "100", "OpenQQ:401-AAA", "OpenQQ-Group:401-G1")

added_keys = []


def slow_sync_once(pair):
    time.sleep(0.30)
    return {"ok": True, "pair": pair.get("old")}


br.sync_once = slow_sync_once


def binder(n):
    time.sleep(0.05 * n)
    p = br.upsert_sync_pair(
        str(2000 + n), "200", "OpenQQ:401-B%d" % n, "OpenQQ-Group:401-G%d" % n
    )
    added_keys.append(br.sync_pair_key(p["old"], p["old_group"], p["current"], p["group"]))


syncer = threading.Thread(target=lambda: br.sync_all(only_due=False))
binders = [threading.Thread(target=binder, args=(n,)) for n in range(1, 6)]
syncer.start()
for t in binders:
    t.start()
syncer.join()
for t in binders:
    t.join()

pairs = br.list_sync_pairs()
keys = {br.sync_pair_key(p["old"], p["old_group"], p["current"], p["group"]) for p in pairs}
missing = [k for k in added_keys if k not in keys]
check(
    not missing,
    "all concurrently-registered pairs survived sync_all (expect %d, got %d, missing %d)"
    % (1 + len(added_keys), len(keys), len(missing)),
)

print()
print("=== 2. concurrent sync_all x2 keeps all pairs ===")
br2, tmp2 = fresh_bridge()
for i in range(4):
    br2.upsert_sync_pair(str(3000 + i), "300", "OpenQQ:401-C%d" % i, "OpenQQ-Group:401-H%d" % i)


def slow2(pair):
    time.sleep(0.10)
    return {"ok": True}


br2.sync_once = slow2
t1 = threading.Thread(target=lambda: br2.sync_all(only_due=False))
t2 = threading.Thread(target=lambda: br2.sync_all(only_due=False))
t1.start(); t2.start(); t1.join(); t2.join()
after = br2.load_sync_config().get("pairs", [])
check(len(after) == 4, "4 pairs still present after concurrent sync_all (got %d)" % len(after))

print()
print("=== 3. concurrent bind + sync keeps every pair, JSON stays valid ===")
br3, tmp3 = fresh_bridge()
errs = []


def worker_bind(n):
    try:
        for i in range(6):
            br3.upsert_sync_pair(
                str(4000 + n), str(400 + n),
                "OpenQQ:401-D%d" % n, "OpenQQ-Group:401-I%d-%d" % (n, i),
            )
    except Exception as e:
        errs.append(repr(e))


def worker_sync():
    try:
        for _ in range(6):
            br3.sync_all(only_due=False)
    except Exception as e:
        errs.append(repr(e))


threads = [threading.Thread(target=worker_bind, args=(n,)) for n in range(4)]
threads += [threading.Thread(target=worker_sync) for _ in range(2)]
for t in threads:
    t.start()
for t in threads:
    t.join()

check(not errs, "no exception during concurrent bind+sync (%s)" % (errs[:3],))
expected = 24
got = len(br3.load_sync_config().get("pairs", []))
check(got == expected, "all %d pairs kept (got %d)" % (expected, got))
leftover = [f for f in os.listdir(tmp3) if f.endswith(".tmp")]
check(not leftover, "no leftover temp files (got %d)" % len(leftover))

print()
print("=" * 56)
print("checks:", CHECKS[0], " failures:", len(FAILS))
if FAILS:
    print("FAILED:", FAILS)
    sys.exit(1)
print("ALL MULTI-BOT CONCURRENCY TESTS PASSED")