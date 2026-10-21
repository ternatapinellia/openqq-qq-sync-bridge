# -*- coding: utf-8 -*-
"""把毫秒时间戳归一化成秒。含备份、dry-run、校验。

用法：
  python normalize_timestamps.py <data.db 路径>            # 预览（不改）
  python normalize_timestamps.py <data.db 路径> --apply    # 实际修改
"""
import os, re, shutil, sqlite3, sys, time

MS_THRESHOLD = 100000000000   # > 1e11 视为毫秒
TIME_SUFFIX = ("_at", "_time")


def scan(path):
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    found = []
    tables = [r["name"] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")]
    for tb in tables:
        cols = [r["name"] for r in con.execute("PRAGMA table_info(%s)" % tb)]
        tcols = [c for c in cols if c.endswith(TIME_SUFFIX)]
        if not tcols:
            continue
        for c in tcols:
            try:
                rows = con.execute(
                    "SELECT rowid AS _rid, %s AS _v FROM %s WHERE %s > ?" % (c, tb, c),
                    (MS_THRESHOLD,)
                ).fetchall()
            except sqlite3.OperationalError:
                # 没有 rowid 的表（WITHOUT ROWID）跳过
                continue
            for r in rows:
                found.append((tb, c, int(r["_rid"]), int(r["_v"])))
    con.close()
    return found


def fix(path, items, apply=False):
    if not items:
        return 0
    if apply:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        backup = path + ".before-tsfix-" + stamp + ".bak"
        con = sqlite3.connect(path)
        dst = sqlite3.connect(backup)
        con.backup(dst)
        dst.close()
        con.close()
        print("已备份: %s" % os.path.basename(backup))
    con = sqlite3.connect(path)
    n = 0
    for tb, c, rowid, v in items:
        newv = v // 1000
        if apply:
            con.execute("UPDATE %s SET %s=? WHERE rowid=?" % (tb, c), (newv, rowid))
        n += 1
    if apply:
        con.commit()
    con.close()
    return n


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    path = sys.argv[1]
    apply = "--apply" in sys.argv
    if not os.path.isfile(path):
        print("找不到文件: %s" % path)
        return
    items = scan(path)
    print("文件: %s" % path)
    print("发现毫秒级时间戳: %d 处\n" % len(items))
    if not items:
        print("无需处理。")
        return
    from collections import Counter
    c = Counter((tb, col) for tb, col, _, _ in items)
    for (tb, col), cnt in sorted(c.items()):
        print("   %-24s %-14s %d 处" % (tb, col, cnt))
    print()
    for tb, col, rowid, v in items[:10]:
        print("   %s.%s rowid=%s  %s -> %s" % (tb, col, rowid, v, v // 1000))
    if len(items) > 10:
        print("   ... 另有 %d 处" % (len(items) - 10))
    n = fix(path, items, apply=apply)
    if apply:
        print("\n已修正 %d 处。" % n)
        left = scan(path)
        print("复查剩余毫秒级: %d 处" % len(left))
    else:
        print("\n这是预览模式，没有改动任何数据。")
        print("确认无误后加 --apply 参数执行。")


if __name__ == "__main__":
    main()