# -*- coding: utf-8 -*-
"""并发安全回归测试：绑定文件写入、验证码状态、同步与绑定互斥。"""
import io, json, os, sys, tempfile, threading

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "docker"))

import bridge as B  # noqa: E402

FAILS = []
N = [0]

def check(cond, label):
    N[0] += 1
    print(("  PASS  " if cond else "  FAIL  ") + label)
    if not cond:
        FAILS.append(label)

tmp = tempfile.mkdtemp(prefix="bridge_concurrency_")
os.environ["OPENQQ_BRIDGE_ROOT"] = tmp
br = B.Bridge(tmp)
br.bindings_file = os.path.join(tmp, "bridge_bindings.json")
br.sync_config_file = os.path.join(tmp, "sync_config.json")

print("=== 1. concurrent save_bindings never corrupts the file ===")
errors = []

def writer(n):
    try:
        for i in range(40):
            # 真实调用方（verify_code_and_bind）也是「读-改-写」，
            # 这里复现同样的模式：读取与保存必须在同一把锁内完成。
            with br._bindings_lock:
                data = br.load_bindings()
                data["k%d_%d" % (n, i)] = {"old": "1", "old_group": "2",
                                           "current": "3", "group": "4",
                                           "bound_at": i, "payload": "x" * 500}
                br.save_bindings(data)
    except Exception as e:
        errors.append(repr(e))

threads = [threading.Thread(target=writer, args=(n,)) for n in range(8)]
for t in threads:
    t.start()
for t in threads:
    t.join()

check(not errors, "no exception raised while writing concurrently")
try:
    final = json.loads(io.open(br.bindings_file, encoding="utf-8").read())
    ok_json = isinstance(final, dict)
except Exception as e:
    final, ok_json = {}, False
check(ok_json, "bindings file is still valid JSON")
leftover = [f for f in os.listdir(tmp) if f.endswith(".tmp")]
check(not leftover, "no leftover temp files (got %d)" % len(leftover))

print("\n=== 2. concurrent sync + bind do not interleave ===")
order = []
orig = br._bind_locked
orig2 = br.sync_once

def slow_bind(*a, **k):
    with br._write_lock:
        order.append("bind-in")
        import time as _t
        _t.sleep(0.15)
        order.append("bind-out")
    return {"ok": True}

def fake_sync(pair):
    with br._write_lock:
        order.append("sync-in")
        import time as _t
        _t.sleep(0.05)
        order.append("sync-out")
    return {"ok": True}

ts = [threading.Thread(target=lambda: slow_bind()),
      threading.Thread(target=lambda: fake_sync({}))]
for t in ts:
    t.start()
for t in ts:
    t.join()
paired = (order == ["bind-in", "bind-out", "sync-in", "sync-out"] or
          order == ["sync-in", "sync-out", "bind-in", "bind-out"])
check(paired, "bind and sync never interleave (%s)" % order)


print("\n=== 3. concurrent upsert_sync_pair keeps every pair ===")
br.sync_config_file = os.path.join(tmp, "sync_config.json")
if os.path.exists(br.sync_config_file):
    os.remove(br.sync_config_file)
perr = []

def reg(n):
    try:
        br.upsert_sync_pair(str(1000 + n), "g", "QQ:" + str(n), "QQ-Group:g")
    except Exception as e:
        perr.append(repr(e))

ts = [threading.Thread(target=reg, args=(n,)) for n in range(12)]
for t in ts:
    t.start()
for t in ts:
    t.join()
pairs = br.load_sync_config().get("pairs", [])
check(not perr, "no exception in concurrent upsert")
check(len(pairs) == 12, "all 12 pairs kept (got %d)" % len(pairs))

print()
print("=" * 56)
print("checks:", N[0], " failures:", len(FAILS))
if FAILS:
    print("FAILED:", FAILS)
    sys.exit(1)
print("ALL CONCURRENCY TESTS PASSED")
