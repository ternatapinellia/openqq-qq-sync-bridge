# -*- coding: utf-8 -*-
import argparse, json, os, sys, tempfile, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "docker"))
sys.path.insert(0, HERE)

import bridge as B
from seadice_fixture import make_data_db, make_logs_db


def build_env(root, bots, groups_per_bot, logs_per_group, items_per_log):
    data_dir = os.path.join(root, "data")
    os.makedirs(data_dir, exist_ok=True)
    make_data_db(os.path.join(data_dir, "data.db"), with_cards=True)
    logs = []
    pairs = []
    for b in range(bots):
        old_qq = str(50000 + b)
        for g in range(groups_per_bot):
            old_gid = "QQ-Group:%d" % (60000 + b * 100 + g)
            for k in range(logs_per_group):
                logs.append({
                    "name": "log-%d-%d-%d" % (b, g, k),
                    "group_id": old_gid,
                    "created_at": 1770000000 + b * 1000 + g * 10 + k,
                    "items": ["msg %d" % i for i in range(items_per_log)],
                })
            pairs.append({
                "old": old_qq,
                "old_group": old_gid.replace("QQ-Group:", ""),
                "current": "OpenQQ:401-B%d-G%d" % (b, g),
                "group": "OpenQQ-Group:401-X%d-%d" % (b, g),
            })
    make_logs_db(os.path.join(data_dir, "data-logs.db"), logs)
    return data_dir, pairs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bots", type=int, default=4)
    ap.add_argument("--groups", type=int, default=5)
    ap.add_argument("--logs", type=int, default=3)
    ap.add_argument("--items", type=int, default=120)
    ap.add_argument("--sync-threads", type=int, default=8)
    ap.add_argument("--rounds", type=int, default=12)
    ap.add_argument("--bind-threads", type=int, default=4)
    ap.add_argument("--bind-count", type=int, default=60)
    args = ap.parse_args()

    root = tempfile.mkdtemp(prefix="bridge_stress_")
    os.environ["OPENQQ_BRIDGE_ROOT"] = root
    data_dir, pairs = build_env(root, args.bots, args.groups, args.logs, args.items)

    br = B.Bridge(data_dir)
    br.bindings_file = os.path.join(root, "bridge_bindings.json")
    br.sync_config_file = os.path.join(root, "sync_config.json")

    print("=" * 62)
    print("Multi-bot stress test")
    print("  bots=%d groups/bot=%d logs/group=%d items/log=%d"
          % (args.bots, args.groups, args.logs, args.items))
    print("  pairs=%d syncThreads=%d rounds=%d bindThreads=%d newPairs=%d"
          % (len(pairs), args.sync_threads, args.rounds,
             args.bind_threads, args.bind_count))
    print("=" * 62)

    for p in pairs:
        br.upsert_sync_pair(p["old"], p["old_group"], p["current"], p["group"])
    print("base pairs registered: %d" % len(br.list_sync_pairs()))

    errors = []

    def sync_worker(tid):
        for _ in range(args.rounds):
            try:
                br.sync_all(only_due=False)
            except Exception as e:
                errors.append("sync[%d] %r" % (tid, e))

    def bind_worker(tid):
        n = args.bind_count // args.bind_threads
        for i in range(n):
            try:
                br.upsert_sync_pair(str(90000 + tid), "700",
                                    "OpenQQ:401-Z%d-%d" % (tid, i),
                                    "OpenQQ-Group:401-Z%d-%d" % (tid, i))
            except Exception as e:
                errors.append("bind[%d] %r" % (tid, e))

    t0 = time.time()
    st = [threading.Thread(target=sync_worker, args=(i,))
          for i in range(args.sync_threads)]
    bt = [threading.Thread(target=bind_worker, args=(i,))
          for i in range(args.bind_threads)]
    for t in st + bt:
        t.start()
    for t in st + bt:
        t.join(timeout=1200)
    elapsed = time.time() - t0

    final = br.list_sync_pairs()
    expected = len(pairs) + (args.bind_count // args.bind_threads) * args.bind_threads
    json_ok = True
    try:
        with open(br.sync_config_file, encoding="utf-8") as f:
            json.load(f)
    except Exception as e:
        json_ok = False
        errors.append("config json: %r" % (e,))
    leftover = [f for f in os.listdir(root) if f.endswith(".tmp")]

    print()
    print("elapsed: %.2fs" % elapsed)
    print("final pairs: %d (expected %d)" % (len(final), expected))
    print("errors: %d" % len(errors))
    print("json valid: %s" % json_ok)
    print("leftover tmp: %d" % len(leftover))

    ok = True
    if errors:
        ok = False
        for e in errors[:5]:
            print("   ", e)
    if len(final) < expected:
        ok = False
        print("  FAIL missing %d pairs" % (expected - len(final)))
    if not json_ok or leftover:
        ok = False

    print()
    print("RESULT:", "PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()