# -*- coding: utf-8 -*-
"""OpenQQ QQ Sync Bridge v3.3 - multi SeaDice instance edition."""
import argparse, json, os, re, sqlite3, threading, time, sys, secrets, smtplib, ssl
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs
from email.message import EmailMessage

VERSION = "3.3"
DEFAULT_PORT = 38999
PORT_FILE_NAME = "bridge_port.txt"

# 备份保留策略：首次迁移快照 1 份（永不覆盖）+ 最近 N 份滚动备份。
BACKUP_KEEP_ROLLING = 2
BACKUP_FIRST_SUFFIX = ".snapshot-first.bak"

# 增量同步：默认间隔 600 秒（10 分钟），最小 30 秒。
SYNC_DEFAULT_INTERVAL = 600
SYNC_CONFIG_NAME = "sync_config.json"


def root_dir():
    # PyInstaller 冻结后 __file__ 指向 _MEI 临时目录，不能从那里找 SeaDice 数据。
    # 应始终以 EXE 所在目录作为桥的工作根目录。
    # Linux/Docker 部署时可用环境变量 OPENQQ_BRIDGE_ROOT 指定配置目录
    # （bridge_port.txt / email_config.json / bridge_bindings.json / bridge_error.log）。
    override = os.environ.get("OPENQQ_BRIDGE_ROOT")
    if override:
        return os.path.abspath(override)
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def path_from_root(p):
    return os.path.normpath(p if os.path.isabs(p) else os.path.join(root_dir(), p))


EMAIL_CONFIG_NAME = "email_config.json"
BINDINGS_FILE_NAME = "bridge_bindings.json"


def to_int(v, default=0):
    """把 sqlite 里可能是 NULL / '' / 数字 / 数字字符串的值安全转成 int。"""
    if v is None:
        return default
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, (int, float)):
        return int(v)
    try:
        t = str(v).strip()
        return int(float(t)) if t else default
    except Exception:
        return default


def mask_email(addr):
    try:
        local, domain = addr.split("@", 1)
        if len(local) <= 2:
            masked = local[0] + "*" * max(1, len(local) - 1)
        else:
            masked = local[0] + "*" * (len(local) - 2) + local[-1]
        return masked + "@" + domain
    except Exception:
        return "******"



def _decode_text(raw):
    """容错解码 SQLite TEXT：优先 UTF-8，失败后退到 GB18030/GBK。

    旧版海豹在某些 Windows 环境下把中文按 GBK 写进库，
    直接用默认 text_factory 会在读取时抛
    "Could not decode to UTF-8 column ..."，导致整个绑定流程 500。
    """
    if raw is None:
        return None
    if isinstance(raw, str):
        return raw
    try:
        return bytes(raw).decode("utf-8")
    except UnicodeDecodeError:
        pass
    for enc in ("gb18030", "gbk", "big5", "latin-1"):
        try:
            return bytes(raw).decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return bytes(raw).decode("utf-8", errors="replace")


def _apply_text_factory(con):
    """让连接用容错解码，避免非 UTF-8 的历史数据直接报错。"""
    con.text_factory = _decode_text
    return con


class Bridge:
    def __init__(self, data_dir):
        self.data_dir = path_from_root(data_dir)
        self.db_path = os.path.join(self.data_dir, "data.db")
        self.logs_path = os.path.join(self.data_dir, "data-logs.db")
        self.port_file = os.path.join(root_dir(), PORT_FILE_NAME)
        self.email_config_file = os.path.join(root_dir(), EMAIL_CONFIG_NAME)
        self.bindings_file = os.path.join(root_dir(), BINDINGS_FILE_NAME)
        self.sync_config_file = os.path.join(root_dir(), SYNC_CONFIG_NAME)
        self.pending_codes = {}
        # 同一桥会被 HTTP 处理线程与同步定时器并发调用。
        self._pending_lock = threading.RLock()
        self._bindings_lock = threading.RLock()
        # 定时同步与绑定操作会写同一批 sqlite 文件，串行化避免互相冲突。
        self._write_lock = threading.RLock()

    def load_email_config(self):
        if not os.path.isfile(self.email_config_file):
            raise RuntimeError(f"email config not found: {self.email_config_file}")
        try:
            with open(self.email_config_file, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception as e:
            raise RuntimeError(f"email config invalid: {e}")
        required = ["sender_email", "smtp_host", "smtp_port", "smtp_password"]
        missing = [k for k in required if not str(cfg.get(k, "")).strip()]
        if missing:
            raise RuntimeError("email config missing: " + ", ".join(missing))
        cfg["smtp_port"] = int(cfg.get("smtp_port", 465))
        cfg["smtp_user"] = str(cfg.get("smtp_user") or cfg["sender_email"]).strip()
        cfg["smtp_ssl"] = bool(cfg.get("smtp_ssl", True))
        return cfg

    def send_verification_email(self, recipient, old, old_group, current, target_group, code):
        cfg = getattr(self, "runtime_email_config", None) or self.load_email_config()
        msg = EmailMessage()
        msg["Subject"] = "OpenQQ旧QQ数据迁移验证码"
        msg["From"] = cfg["sender_email"]
        msg["To"] = recipient
        msg.set_content(
            "OpenQQ 旧QQ数据迁移验证\n\n"
            f"旧QQ：{old}\n"
            f"旧群：{old_group}\n"
            f"当前OpenQQ用户：{current}\n"
            f"当前群：{target_group}\n\n"
            f"验证码：{code}\n\n"
            "验证码有效期：5分钟。\n"
            "如果不是你本人发起的操作，请忽略此邮件。"
        )
        if cfg["smtp_ssl"]:
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(cfg["smtp_host"], cfg["smtp_port"], context=context, timeout=30) as s:
                s.login(cfg["smtp_user"], cfg["smtp_password"])
                s.send_message(msg)
        else:
            with smtplib.SMTP(cfg["smtp_host"], cfg["smtp_port"], timeout=30) as s:
                s.ehlo()
                if cfg.get("smtp_starttls", True):
                    s.starttls(context=ssl.create_default_context())
                    s.ehlo()
                s.login(cfg["smtp_user"], cfg["smtp_password"])
                s.send_message(msg)

    def binding_key(self, old, old_group, current="", target_group=""):
        """同一个旧QQ可以绑多个 OpenQQ；只有完全相同的配对才算重复。"""
        if current or target_group:
            return f"{old}|{old_group}|{current}|{target_group}"
        return f"{old}|{old_group}"

    def _lookup_binding(self, bindings, old, old_group, current, target_group):
        """查找绑定记录，兼容升级前的旧键格式（old|old_group）。

        旧格式的键里没有 OpenQQ 信息，但值里存了 current / group，
        所以仍能判断这条记录是不是同一个配对。
        返回 (命中的键, 记录或 None, 是否为旧格式)。
        """
        key = self.binding_key(old, old_group, current, target_group)
        rec = bindings.get(key)
        if rec:
            return key, rec, False
        legacy_key = f"{old}|{old_group}"
        legacy = bindings.get(legacy_key)
        if legacy and str(legacy.get("current", "")) == str(current) \
                and str(legacy.get("group", "")) == str(target_group):
            return legacy_key, legacy, True
        return key, None, False

    def load_bindings(self):
        with self._bindings_lock:
            try:
                with open(self.bindings_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return data if isinstance(data, dict) else {}
            except Exception:
                return {}

    def save_bindings(self, data):
        # 每次用唯一的临时文件再原子替换：多个线程共用同一个 .tmp
        # 会互相截断，产生非法 JSON 导致绑定记录丢失。
        with self._bindings_lock:
            tmp = "%s.%d.%d.tmp" % (self.bindings_file, os.getpid(), threading.get_ident())
            try:
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp, self.bindings_file)
                tmp = None
            finally:
                # 成功后 tmp 已改名，不能再删（否则可能删掉别的线程刚写的文件）。
                if tmp and os.path.exists(tmp):
                    try:
                        os.remove(tmp)
                    except OSError:
                        pass

    def set_email_config(self, cfg):
        required = ["sender_email", "smtp_host", "smtp_port", "smtp_password"]
        missing = [k for k in required if not str(cfg.get(k, "")).strip()]
        if missing:
            raise RuntimeError("邮箱配置缺少：" + ", ".join(missing))
        sender = str(cfg.get("sender_email", "")).strip()
        if "@" not in sender or "." not in sender.rsplit("@", 1)[-1]:
            raise RuntimeError("发件邮箱格式不正确")
        port = int(cfg.get("smtp_port", 465))
        if not 1 <= port <= 65535:
            raise RuntimeError("SMTP端口不正确")
        self.runtime_email_config = {
            "sender_email": sender,
            "smtp_user": str(cfg.get("sender_email") or sender).strip(),
            "smtp_host": str(cfg.get("smtp_host") or "smtp.qq.com").strip(),
            "smtp_port": port,
            "smtp_password": str(cfg.get("smtp_password") or ""),
            "smtp_ssl": bool(cfg.get("smtp_ssl", True)),
        }
        return {"ok": True, "email": mask_email(sender)}

    def get_runtime_email_config(self):
        cfg = getattr(self, "runtime_email_config", None)
        if not cfg:
            raise RuntimeError("请先在SeaDice插件配置中填写邮箱设置")
        return cfg

    def send_email_message(self, msg):
        """统一SMTP发送流程；测试邮件与验证码邮件使用完全相同的连接/认证逻辑。"""
        cfg = getattr(self, "runtime_email_config", None) or self.load_email_config()
        if cfg.get("smtp_ssl", True):
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(cfg["smtp_host"], cfg["smtp_port"], context=context, timeout=30) as s:
                s.ehlo()
                s.login(cfg["smtp_user"], cfg["smtp_password"])
                s.send_message(msg)
        else:
            with smtplib.SMTP(cfg["smtp_host"], cfg["smtp_port"], timeout=30) as s:
                s.ehlo()
                if cfg.get("smtp_starttls", True):
                    s.starttls(context=ssl.create_default_context())
                    s.ehlo()
                s.login(cfg["smtp_user"], cfg["smtp_password"])
                s.send_message(msg)

    def send_test_email(self):
        cfg = self.get_runtime_email_config()
        msg = EmailMessage()
        msg["Subject"] = "OpenQQ QQ Sync Bridge 邮箱测试"
        msg["From"] = cfg["sender_email"]
        msg["To"] = cfg["sender_email"]
        msg.set_content("这是 OpenQQ QQ Sync Bridge 的测试邮件。\n\n如果你能收到这封邮件，说明发件邮箱和 SMTP 授权码配置正确。")
        self.send_email_message(msg)
        return {"ok": True, "email": mask_email(cfg["sender_email"])}

    def request_code(self, old, old_group, current, target_group):
        # ThreadingHTTPServer 并发处理请求，pending_codes 必须加锁。
        with self._pending_lock:
            return self._request_code_locked(old, old_group, current, target_group)

    def _request_code_locked(self, old, old_group, current, target_group):
        bindings = self.load_bindings()
        key, existing, is_legacy = self._lookup_binding(
            bindings, old, old_group, current, target_group)
        if existing:
            # 只有完全相同的配对才算重复；同一个旧QQ绑到别的 OpenQQ 是允许的。
            raise RuntimeError(
                "该旧QQ/旧群已经绑定到当前OpenQQ，无需重复绑定。"
                "如需绑定到另一个 OpenQQ，直接执行 .旧QQ绑定 即可。"
            )

        # Confirm source data exists before sending mail.
        # 第 6 条（本次修复）：原版只要没有角色卡就直接拒绝，
        # 但很多人只用过网页/手机版本，没有角色卡、却有大量 log。
        # log 是挂在群上的，本来就不需要角色卡，因此这里改为
        # “角色卡或 log 至少有一边有数据”才放行；两边都空时才拒绝。
        info = self.lookup(old)
        char_count = int(info.get("character_count") or 0)
        log_count = self.count_group_logs(old_group)
        if char_count <= 0 and log_count <= 0:
            raise RuntimeError("该旧QQ与该旧群都没有找到可迁移的数据（角色卡和 log 均为空）。")

        code = f"{secrets.randbelow(1000000):06d}"
        now = time.time()
        pending_key = f"{old}|{old_group}|{current}|{target_group}"
        recipient = f"{old}@qq.com"
        self.send_verification_email(recipient, old, old_group, current, target_group, code)
        self.pending_codes[pending_key] = {
            "code": code,
            "expires": now + 300,
            "attempts": 0,
            "old": old,
            "old_group": old_group,
            "current": current,
            "group": target_group,
        }
        return {"ok": True, "email": mask_email(recipient), "expires_in": 300}

    def verify_code_and_bind(self, old, old_group, current, target_group, code):
        with self._pending_lock:
            return self._verify_code_and_bind_locked(old, old_group, current, target_group, code)

    def _verify_code_and_bind_locked(self, old, old_group, current, target_group, code):
        pending_key = f"{old}|{old_group}|{current}|{target_group}"
        item = self.pending_codes.get(pending_key)
        if not item:
            raise RuntimeError("没有找到待验证的请求，请重新执行 .旧QQ绑定。")
        if time.time() > item["expires"]:
            self.pending_codes.pop(pending_key, None)
            raise RuntimeError("验证码已过期，请重新获取。")
        item["attempts"] += 1
        if item["attempts"] > 5:
            self.pending_codes.pop(pending_key, None)
            raise RuntimeError("验证码错误次数过多，请重新获取。")
        if not secrets.compare_digest(str(code).strip(), item["code"]):
            remain = max(0, 5 - item["attempts"])
            raise RuntimeError(f"验证码错误，还可尝试 {remain} 次。")

        bindings = self.load_bindings()
        key, existing, is_legacy = self._lookup_binding(
            bindings, old, old_group, current, target_group)
        legacy_old_key = f"{old}|{old_group}"
        if existing:
            self.pending_codes.pop(pending_key, None)
            raise RuntimeError(
                "该旧QQ/旧群已经绑定到当前OpenQQ，无需重复绑定。"
                "如需绑定到另一个 OpenQQ，直接执行 .旧QQ绑定 即可。"
            )

        result = self.bind(old, current, target_group, old_group)
        # 用新键写入；如果之前是旧键格式，顺便迁移掉，避免文件里堆积死记录。
        if is_legacy and key != legacy_old_key:
            bindings.pop(legacy_old_key, None)
        bindings[key] = {
            "old": str(old),
            "old_group": str(old_group),
            "current": current,
            "group": target_group,
            "bound_at": int(time.time()),
        }
        self.save_bindings(bindings)
        # 绑定成功后自动登记增量同步关系（默认开启，定时器会按间隔跑）
        try:
            pair = self.upsert_sync_pair(old, old_group, current, target_group, enabled=True)
            result["sync"] = {
                "registered": True,
                "enabled": bool(pair.get("enabled", True)),
                "interval": int(pair.get("interval") or SYNC_DEFAULT_INTERVAL),
            }
        except Exception as e:
            self.log_error("register sync pair failed: %s: %s" % (type(e).__name__, e))
            result["sync"] = {"registered": False, "error": str(e)}
        self.pending_codes.pop(pending_key, None)
        return result

    def check(self):
        if not os.path.isfile(self.db_path):
            raise RuntimeError(f"data.db not found: {self.db_path}")
        if not os.path.isfile(self.logs_path):
            raise RuntimeError(f"data-logs.db not found: {self.logs_path}")

    def connect(self, path):
        self.check()
        con = _apply_text_factory(sqlite3.connect(path, timeout=30))
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA busy_timeout=30000")
        return con

    def _snapshot_sqlite(self, src_path, dest_path):
        # Use SQLite backup API so WAL contents are included in the snapshot.
        src = _apply_text_factory(sqlite3.connect(src_path, timeout=30))
        try:
            dst = _apply_text_factory(sqlite3.connect(dest_path))
            try:
                src.backup(dst)
            finally:
                dst.close()
        finally:
            src.close()

    def _prune_rolling_backups(self, src_path):
        """只保留最近 BACKUP_KEEP_ROLLING 份滚动备份；首次快照永不删除。"""
        folder = os.path.dirname(os.path.abspath(src_path)) or "."
        prefix = os.path.basename(src_path) + ".before-sync-"
        rolling = []
        try:
            for name in os.listdir(folder):
                if name.startswith(prefix) and name.endswith(".bak"):
                    rolling.append(os.path.join(folder, name))
        except Exception:
            return
        # 文件名内含时间戳，按名字排序即为时间顺序。
        rolling.sort()
        for old in rolling[:-BACKUP_KEEP_ROLLING] if BACKUP_KEEP_ROLLING > 0 else rolling:
            try:
                os.remove(old)
            except Exception:
                pass

    def backup_db_before_bind(self, label=""):
        """备份 data.db：首次迁移留 1 份永久快照，另保留最近 N 份滚动备份。"""
        first = self.db_path + BACKUP_FIRST_SUFFIX
        stamp = time.strftime("%Y%m%d-%H%M%S")
        if not os.path.exists(first):
            tmp = first + ".tmp"
            try:
                self._snapshot_sqlite(self.db_path, tmp)
                os.replace(tmp, first)
            except Exception:
                try:
                    if os.path.exists(tmp):
                        os.remove(tmp)
                except Exception:
                    pass
                raise
        rolling = f"{self.db_path}.before-sync-{stamp}{('-'+label) if label else ''}.bak"
        try:
            self._snapshot_sqlite(self.db_path, rolling)
        except Exception:
            # 滚动备份失败不应阻断迁移；首次快照已尽力保存。
            return first if os.path.exists(first) else rolling
        self._prune_rolling_backups(self.db_path)
        return rolling

    def backup_logs_before_bind(self, label=""):
        """备份 data-logs.db：策略同 data.db，但两者各自独立计数。"""
        first = self.logs_path + BACKUP_FIRST_SUFFIX
        stamp = time.strftime("%Y%m%d-%H%M%S")
        if not os.path.exists(first):
            tmp = first + ".tmp"
            try:
                self._snapshot_sqlite(self.logs_path, tmp)
                os.replace(tmp, first)
            except Exception:
                try:
                    if os.path.exists(tmp):
                        os.remove(tmp)
                except Exception:
                    pass
                raise
        rolling = f"{self.logs_path}.before-sync-{stamp}{('-'+label) if label else ''}.bak"
        try:
            self._snapshot_sqlite(self.logs_path, rolling)
        except Exception:
            return first if os.path.exists(first) else rolling
        self._prune_rolling_backups(self.logs_path)
        return rolling
    @staticmethod
    def row_dict(row):
        return dict(row) if row else None

    def log_error(self, message):
        try:
            stamp = time.strftime("%Y-%m-%d %H:%M:%S")
            with open(os.path.join(self.data_dir, "bridge_error.log"), "a", encoding="utf-8") as f:
                f.write(f"[{stamp}] {message}\n")
        except Exception:
            pass

    def save_port(self, port):
        if not 1 <= int(port) <= 65535:
            raise RuntimeError("Invalid port")
        tmp = self.port_file + ".tmp"
        with open(tmp, "w", encoding="utf-8", newline="") as f:
            f.write(str(int(port)) + "\n")
        os.replace(tmp, self.port_file)
        return int(port)

    def read_saved_port(self):
        try:
            with open(self.port_file, "r", encoding="utf-8") as f:
                p = int(f.read().strip())
                if 1 <= p <= 65535:
                    return p
        except Exception:
            pass
        return DEFAULT_PORT

    def count_group_logs(self, old_group):
        """统计旧群里可迁移的 log 数量（只读，不改动数据）。"""
        try:
            if not os.path.isfile(self.logs_path):
                return 0
            group_id = old_group if str(old_group).startswith("QQ-Group:") else ("QQ-Group:" + str(old_group))
            con = _apply_text_factory(sqlite3.connect("file:%s?mode=ro" % self.logs_path.replace("\\", "/"), uri=True))
            try:
                row = con.execute("SELECT COUNT(*) FROM logs WHERE group_id=?", (group_id,)).fetchone()
                return int(row[0] or 0) if row else 0
            finally:
                con.close()
        except Exception:
            # 读不到就当没有 log，交给上层决定是否放行。
            return 0

    def lookup(self, old):
        owner = "QQ:" + old
        # 注意：sqlite3 的 with 只提交事务，不会关闭连接。
        # 必须显式 close()，否则每次查询泄漏一个连接，
        # 持有读事务会阻塞海豹的 WAL checkpoint，导致 -wal 膨胀。
        con = self.connect(self.db_path)
        try:
            rows = con.execute(
                "SELECT id, attrs_type, binding_sheet_id, name, owner_id, sheet_type, "
                "is_hidden, created_at, updated_at, length(data) AS data_size "
                "FROM attrs WHERE owner_id=? ORDER BY updated_at DESC", (owner,)
            ).fetchall()
        finally:
            con.close()
        chars = [dict(r) for r in rows if r["attrs_type"] in ("character", "coc7", "dnd5e", "st") or (r["name"] and r["data_size"] is not None)]
        return {"ok": True, "characters": chars, "character_count": len(chars)}

    def _unique_log_name(self, con, target_group, name):
        """在目标群里找一个不冲突的 log 名（数据库要求 name+group_id 唯一）。"""
        base = (name or "未命名记录").strip() or "未命名记录"
        candidate = base
        n = 2
        while con.execute(
            "SELECT 1 FROM logs WHERE group_id=? AND name=?", (target_group, candidate)
        ).fetchone():
            candidate = f"{base} ({n})"
            n += 1
        return candidate

    def _find_migrated_log(self, con, target_group, title, created_at, item_count):
        """判断某条旧 log 是否在目标群里已经迁移过（用于重复执行时的幂等）。

        必须同时满足三个条件，避免把旧库里 created_at=0 之类的无关记录误判成重复：
        1. created_at 相同；
        2. 目标群存在同名记录，或名为“原名 (n)”（上次因撞名自动改名的结果）；
        3. 该记录的 log_items 条数与源 log 的条数一致。
        """
        base = (title or "").strip() or "未命名记录"
        rows = con.execute(
            "SELECT id,name FROM logs WHERE group_id=? AND created_at=?",
            (target_group, created_at),
        ).fetchall()
        for row in rows:
            name = row["name"] or ""
            if name != base:
                if not name.startswith(base + " ("):
                    continue
                tail = name[len(base) + 2:]
                if not (tail.endswith(")") and tail[:-1].isdigit()):
                    continue
            n = con.execute(
                "SELECT COUNT(*) FROM log_items WHERE log_id=?", (to_int(row["id"]),)
            ).fetchone()[0]
            if int(n or 0) == int(item_count):
                return to_int(row["id"])
        return None

    def migrate_logs(self, old_group_id, target_group):
        """Copy logs/log_items from old_group_id to target_group with remapped IDs.

        第 7 条（本次修复）：原版把全部 log 放在同一个事务里，只要有一条出错
        （空记录、关联异常、重名、数据库约束等）就整批回滚，表现为“19 份只成功 1 份”。
        现在改为逐条 log 独立提交：单条失败只跳过该条并记录原因，其余照常迁移。
        同名 log 改为自动改名保留（追加 “ (2)” 等），不再丢弃内容。
        """
        if not os.path.isfile(self.logs_path):
            raise RuntimeError(f"data-logs.db not found: {self.logs_path}")

        con = _apply_text_factory(sqlite3.connect(self.logs_path, timeout=30))
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA busy_timeout=30000")
        try:
            old_logs = con.execute(
                "SELECT id,name,group_id,created_at,updated_at,size,extra,upload_url,upload_time "
                "FROM logs WHERE group_id=? ORDER BY id ASC", (old_group_id,)
            ).fetchall()
            if not old_logs:
                return {"log_count": 0, "log_item_count": 0, "log_skipped": 0,
                        "log_failed": 0, "log_errors": []}

            copied_logs = 0
            copied_items = 0
            skipped_logs = 0
            failed_logs = 0
            errors = []

            for log in old_logs:
                src_log_id = int(log["id"])
                title = log["name"] or ""
                try:
                    # 逐条独立事务：一条失败不影响其它 log。
                    con.execute("BEGIN IMMEDIATE")
                    # 先数一下源 log 的条目数：重复执行时用“同名+同时间+同条目数”
                    # 判断是否已经迁移过，避免改名后的记录被再次复制一份。
                    src_item_count = int(con.execute(
                        "SELECT COUNT(*) FROM log_items WHERE log_id=?", (src_log_id,)
                    ).fetchone()[0] or 0)
                    if self._find_migrated_log(con, target_group, title, log["created_at"], src_item_count):
                        con.commit()
                        skipped_logs += 1
                        continue

                    new_name = self._unique_log_name(con, target_group, title)
                    max_log_id = int(
                        con.execute("SELECT COALESCE(MAX(id),0) FROM logs").fetchone()[0] or 0
                    )
                    new_log_id = max_log_id + 1
                    con.execute(
                        "INSERT INTO logs(id,name,group_id,created_at,updated_at,size,extra,upload_url,upload_time) "
                        "VALUES(?,?,?,?,?,?,?,?,?)",
                        (new_log_id, new_name, target_group, log["created_at"], log["updated_at"],
                         log["size"], log["extra"], log["upload_url"], log["upload_time"]),
                    )

                    items = con.execute(
                        "SELECT id,log_id,group_id,nickname,im_userid,time,message,is_dice,command_id,"
                        "command_info,raw_msg_id,user_uniform_id,removed,parent_id "
                        "FROM log_items WHERE log_id=? ORDER BY id ASC", (src_log_id,)
                    ).fetchall()

                    next_item_id = int(
                        con.execute("SELECT COALESCE(MAX(id),0) FROM log_items").fetchone()[0] or 0
                    )
                    item_map = {}
                    for item in items:
                        next_item_id += 1
                        item_map[int(item["id"])] = next_item_id
                        con.execute(
                            "INSERT INTO log_items(id,log_id,group_id,nickname,im_userid,time,message,is_dice,"
                            "command_id,command_info,raw_msg_id,user_uniform_id,removed,parent_id) "
                            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                            (next_item_id, new_log_id, target_group, item["nickname"], item["im_userid"],
                             item["time"], item["message"], item["is_dice"], item["command_id"],
                             item["command_info"], item["raw_msg_id"], item["user_uniform_id"],
                             item["removed"],
                             item_map.get(int(item["parent_id"])) if item["parent_id"] is not None else None),
                        )
                    con.commit()
                    copied_logs += 1
                    copied_items += len(items)
                except Exception as e:
                    try:
                        con.rollback()
                    except Exception:
                        pass
                    failed_logs += 1
                    errors.append(f"{title or src_log_id}: {type(e).__name__}: {e}")
                    self.log_error(
                        f"Log item migration failed (group {old_group_id} -> {target_group}, "
                        f"log id {src_log_id} {title!r}): {type(e).__name__}: {e}"
                    )
                    continue

            return {
                "log_count": copied_logs,
                "log_item_count": copied_items,
                "log_skipped": skipped_logs,
                "log_failed": failed_logs,
                "log_errors": errors[:10],
            }
        finally:
            con.close()
    # ==================================================================
    # 增量同步（v3.1）
    #   log      : 双向增量，只追加新条目，不改已有内容
    #   角色卡   : 只增不改（已存在的按 id 跳过）
    #   PC 数据  : 单向 OpenQQ -> 旧QQ，覆盖前先备份，并比较 updated_at
    # ==================================================================

    def load_sync_config(self):
        with self._bindings_lock:
            try:
                with open(self.sync_config_file, "r", encoding="utf-8") as f:
                    d = json.load(f)
                return d if isinstance(d, dict) else {}
            except Exception:
                return {}

    def save_sync_config(self, d):
        tmp = "%s.%d.%d.tmp" % (self.sync_config_file, os.getpid(), threading.get_ident())
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.sync_config_file)

    @staticmethod
    def sync_pair_key(old, old_group, current, target_group):
        return f"{old}|{old_group}|{current}|{target_group}"

    def list_sync_pairs(self):
        cfg = self.load_sync_config()
        pairs = cfg.get("pairs")
        if not isinstance(pairs, list):
            return []
        out = []
        for p in pairs:
            if not isinstance(p, dict):
                continue
            if not all(str(p.get(k) or "").strip() for k in ("old", "old_group", "current", "group")):
                continue
            out.append(p)
        return out

    def upsert_sync_pair(self, old, old_group, current, target_group, enabled=True):
        """登记 / 更新一条同步关系。返回该条记录。"""
        with self._bindings_lock:
            return self._upsert_sync_pair_locked(old, old_group, current, target_group, enabled)

    def _upsert_sync_pair_locked(self, old, old_group, current, target_group, enabled=True):
        cfg = self.load_sync_config()
        pairs = [p for p in cfg.get("pairs", []) if isinstance(p, dict)]
        key = self.sync_pair_key(old, old_group, current, target_group)
        found = None
        for p in pairs:
            if self.sync_pair_key(p.get("old"), p.get("old_group"), p.get("current"),
                                  p.get("group")) == key:
                found = p
                break
        if found is None:
            found = {
                "old": str(old), "old_group": str(old_group),
                "current": str(current), "group": str(target_group),
                "enabled": bool(enabled),
                "interval": SYNC_DEFAULT_INTERVAL,
                "created_at": int(time.time()),
                "last_run": 0,
                "last_result": None,
            }
            pairs.append(found)
        else:
            found["enabled"] = bool(enabled)
        cfg["pairs"] = pairs
        self.save_sync_config(cfg)
        return found

    def remove_sync_pair(self, old, old_group, current, target_group):
        with self._bindings_lock:
            return self._remove_sync_pair_locked(old, old_group, current, target_group)

    def _remove_sync_pair_locked(self, old, old_group, current, target_group):
        cfg = self.load_sync_config()
        key = self.sync_pair_key(old, old_group, current, target_group)
        pairs = [p for p in cfg.get("pairs", []) if isinstance(p, dict)
                 and self.sync_pair_key(p.get("old"), p.get("old_group"), p.get("current"),
                                        p.get("group")) != key]
        cfg["pairs"] = pairs
        self.save_sync_config(cfg)
        return len(pairs)

    def _rolling_backup(self, src_path, label="sync"):
        """同步前的滚动备份：只保留最近 N 份，不动首次快照。"""
        stamp = time.strftime("%Y%m%d-%H%M%S")
        rolling = f"{src_path}.before-sync-{stamp}{('-'+label) if label else ''}.bak"
        try:
            self._snapshot_sqlite(src_path, rolling)
        except Exception:
            return None
        self._prune_rolling_backups(src_path)
        return rolling

    # ---------------------- log 增量 ----------------------

    _to_int = staticmethod(to_int)

    @staticmethod
    def _strip_copy_suffix(name):
        """剥掉所有结尾的「 (n)」复制后缀。'甲 (2) (3)' -> '甲'"""
        n = (name or "").strip()
        while True:
            mm = re.match(r"^(.*)\s+\((\d+)\)$", n)
            if not mm:
                break
            n = mm.group(1).strip()
        return n

    def _match_log(self, con, group_id, name, created_at):
        """在目标群里找「同一条 log」。

        判定：把名字的 (n) 后缀全部剥掉后相同，且 created_at 相同。
        多条命中时取条目数最多的那条（避免误配到空壳）。
        """
        base = self._strip_copy_suffix(name) or "未命名记录"
        want_ca = to_int(created_at, 0)
        hits = []
        for row in con.execute(
            "SELECT id,name,created_at FROM logs WHERE group_id=?", (group_id,)
        ).fetchall():
            if to_int(row["created_at"], 0) != want_ca:
                continue
            if self._strip_copy_suffix(row["name"]) != base:
                continue
            hits.append(int(row["id"]))
        if not hits:
            return None
        if len(hits) == 1:
            return hits[0]
        # 多条时取条目数最多的
        best = None
        best_n = -1
        for lid in hits:
            n = int(con.execute(
                "SELECT COUNT(*) FROM log_items WHERE log_id=?", (lid,)
            ).fetchone()[0] or 0)
            if n > best_n:
                best_n = n
                best = lid
        return best

    def _next_log_id(self, con):
        return int(con.execute("SELECT COALESCE(MAX(id),0) FROM logs").fetchone()[0] or 0) + 1

    def _next_item_id(self, con):
        return int(con.execute("SELECT COALESCE(MAX(id),0) FROM log_items").fetchone()[0] or 0) + 1

    def _append_log_items(self, con, src_log_id, dst_log_id, dst_group):
        """把源 log 中「目标还没有的」条目追加过去。返回追加条数。"""
        items = con.execute(
            "SELECT id,log_id,group_id,nickname,im_userid,time,message,is_dice,command_id,"
            "command_info,raw_msg_id,user_uniform_id,removed,parent_id "
            "FROM log_items WHERE log_id=? ORDER BY id ASC", (to_int(src_log_id),)
        ).fetchall()
        have = int(con.execute(
            "SELECT COUNT(*) FROM log_items WHERE log_id=?", (to_int(dst_log_id),)
        ).fetchone()[0] or 0)
        if len(items) <= have:
            return 0
        todo = items[have:]
        # 目标库里已有的条目 id，用于 parent_id 映射
        existing = con.execute(
            "SELECT id FROM log_items WHERE log_id=? ORDER BY id ASC", (to_int(dst_log_id),)
        ).fetchall()
        id_map = {}
        for i, row in enumerate(existing):
            if i < len(items):
                id_map[int(items[i]["id"])] = to_int(row["id"])
        next_id = self._next_item_id(con)
        added = 0
        for it in todo:
            next_id += 1
            id_map[to_int(it["id"])] = next_id
            parent = it["parent_id"]
            parent_new = None
            if parent is not None and str(parent).strip() != "":
                parent_new = id_map.get(to_int(parent, None))
            con.execute(
                "INSERT INTO log_items(id,log_id,group_id,nickname,im_userid,time,message,is_dice,"
                "command_id,command_info,raw_msg_id,user_uniform_id,removed,parent_id) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (next_id, to_int(dst_log_id), dst_group, it["nickname"], it["im_userid"], it["time"],
                 it["message"], it["is_dice"], it["command_id"], it["command_info"],
                 it["raw_msg_id"], it["user_uniform_id"], it["removed"], parent_new),
            )
            added += 1
        return added

    def sync_logs_direction(self, con, src_group, dst_group):
        """把 src_group 比 dst_group 多的内容追加过去。只增不改。"""
        stats = {"new_logs": 0, "appended_logs": 0, "items": 0, "failed": 0, "errors": []}
        rows = con.execute(
            "SELECT id,name,created_at,updated_at,size,extra,upload_url,upload_time "
            "FROM logs WHERE group_id=? ORDER BY id ASC", (src_group,)
        ).fetchall()
        for lg in rows:
            src_id = to_int(lg["id"])
            title = lg["name"] or ""
            try:
                con.execute("BEGIN IMMEDIATE")
                dst_id = self._match_log(con, dst_group, lg["name"], lg["created_at"])
                if dst_id is None:
                    # 目标没有这条 log -> 整条复制（名字冲突则改名）
                    new_name = self._unique_log_name(con, dst_group, title)
                    new_id = self._next_log_id(con)
                    con.execute(
                        "INSERT INTO logs(id,name,group_id,created_at,updated_at,size,extra,"
                        "upload_url,upload_time) VALUES(?,?,?,?,?,?,?,?,?)",
                        (new_id, new_name, dst_group, lg["created_at"], lg["updated_at"],
                         lg["size"], lg["extra"], lg["upload_url"], lg["upload_time"]),
                    )
                    added = self._append_log_items(con, src_id, new_id, dst_group)
                    con.commit()
                    stats["new_logs"] += 1
                    stats["items"] += added
                else:
                    added = self._append_log_items(con, src_id, dst_id, dst_group)
                    if added:
                        # 同步把 size / updated_at 顶到源那边的值
                        con.execute(
                            "UPDATE logs SET size=?, updated_at=? WHERE id=?",
                            (lg["size"], lg["updated_at"], dst_id),
                        )
                        con.commit()
                        stats["appended_logs"] += 1
                        stats["items"] += added
                    else:
                        con.commit()
            except Exception as e:
                try:
                    con.rollback()
                except Exception:
                    pass
                stats["failed"] += 1
                if len(stats["errors"]) < 10:
                    stats["errors"].append("%s: %s: %s" % (title or src_id, type(e).__name__, e))
                self.log_error("sync_logs_direction %s -> %s log %s (%r): %s: %s"
                               % (src_group, dst_group, src_id, title, type(e).__name__, e))
                continue
        return stats

    def sync_logs_pair(self, con, old_group_id, target_group):
        """双向增量：先旧->新，再新->旧。"""
        fwd = self.sync_logs_direction(con, old_group_id, target_group)
        back = self.sync_logs_direction(con, target_group, old_group_id)
        return {"forward": fwd, "backward": back}

    # ---------------------- 角色卡 / PC 数据 ----------------------

    def sync_cards_add_only(self, con, old_owner, current):
        """旧QQ 的角色卡只增不改地补到 OpenQQ 名下。返回新增张数。"""
        added = 0
        rows = con.execute(
            "SELECT id,data,attrs_type,binding_sheet_id,name,owner_id,sheet_type,is_hidden,"
            "created_at,updated_at FROM attrs"
        ).fetchall()
        src = [r for r in rows if str(r["owner_id"] or "") == old_owner]
        for a in src:
            raw = bytes(a["data"] or b"")
            if len(raw) <= 23:
                continue
            new_id = str(a["id"]) + "-openqq-" + current.replace(":", "_")
            if con.execute("SELECT 1 FROM attrs WHERE id=?", (new_id,)).fetchone():
                continue  # 已存在 -> 不动
            con.execute(
                "INSERT INTO attrs(id,data,attrs_type,binding_sheet_id,name,owner_id,sheet_type,"
                "is_hidden,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (new_id, raw, a["attrs_type"], "", a["name"], current, a["sheet_type"],
                 a["is_hidden"], a["created_at"], int(time.time())),
            )
            added += 1
        return added

    def _find_openqq_state_for(self, con, old_owner, old_group_id):
        """找出 OpenQQ 侧、与「该旧QQ + 该旧群」对应的那份 PC 状态。
        两种情况：
          1. 迁移时写下的 QQ-Group:<群>-OpenQQ:<user>
          2. 用户在 OpenQQ 群里打了 .pc 后产生的 OpenQQ-Group:<...>-OpenQQ:<user>
        """
        cands = []
        for r in con.execute(
            "SELECT id,data,updated_at,owner_id,binding_sheet_id,attrs_type FROM attrs"
        ).fetchall():
            i = str(r["id"] or "")
            ow = str(r["owner_id"] or "")
            if not ow.startswith("OpenQQ:"):
                continue
            if r["attrs_type"] == "character":
                continue
            # 形如 QQ-Group:<群>-OpenQQ:<用户>
            if i.startswith(old_group_id + "-OpenQQ:"):
                cands.append(r)
            # 形如 OpenQQ-Group:... 且 owner 是当前用户 -> 也算（用户后来在官方群打的）
            elif i.startswith("OpenQQ-Group:") and i.endswith("-" + ow):
                cands.append(r)
        if not cands:
            return None
        return max(cands, key=lambda r: self._norm_ts(r["updated_at"]))

    @staticmethod
    def _norm_ts(v):
        """把时间戳归一化成秒。

        海豹统一用秒，但历史版本的本工具曾误写过毫秒，
        所以大于 1e11 的值按毫秒处理，避免新旧数据比较错乱。
        """
        n = Bridge._to_int(v, 0)
        if n > 100000000000:      # > 1e11 视为毫秒
            n = n // 1000
        return n

    @staticmethod
    def _load_pc_dict(raw):
        """把 attrs.data 解析成 {"字段": 值} 形态；失败返回 None。"""
        try:
            doc = json.loads(bytes(raw or b"").decode("utf-8"))
            d = doc["v"]["dict"]
            return d if isinstance(d, dict) else None
        except Exception:
            return None

    @staticmethod
    def _field_value(entry):
        """取字段的原始值（海豹的格式是 {"t":0,"v":51}）。"""
        if isinstance(entry, dict):
            return entry.get("v")
        return entry

    @staticmethod
    def _pc_equal(a, b):
        """比较两个 PC 字典内容是否等价（不比字节，比字段值）。"""
        if a == b:
            return True
        if not a and not b:
            return True
        if not a or not b:
            return False
        if set(a.keys()) != set(b.keys()):
            return False
        for k in a:
            if Bridge._field_value(a[k]) != Bridge._field_value(b[k]):
                return False
        return True

    @staticmethod
    def _build_pc_data(fields):
        raw = json.dumps({"t": 7, "v": {"dict": fields}},
                         ensure_ascii=False, separators=(",", ":"))
        return raw.encode("utf-8")

    def merge_pc_fields(self, con, old_owner, old_group_id, current):
        """按字段合并两边的 PC 数据，双向都补齐。

        规则：
          * 两边都有的字段 -> 取 updated_at 较新那一侧的整份字典里的值
          * 只有一边有的字段 -> 直接补到另一边
          * 单独某个字段没有自己的时间戳，所以以「这份 PC 行整体的 updated_at」
            作为该行所有字段的时间依据（海豹就是这么存的）
          * 合并后如果内容没变，不写库，也不会改动 updated_at
        """
        res = {"action": "none", "added_to_old": 0, "added_to_new": 0,
               "old_len": None, "new_len": None, "old_ms": 0, "new_ms": 0}

        src = self._find_openqq_state_for(con, old_owner, old_group_id)
        src_id = str(src["id"]) if src is not None else None
        src_dict = self._load_pc_dict(src["data"]) if src is not None else None
        new_ms = self._norm_ts(src["updated_at"]) if src is not None else 0

        tgt_id = old_group_id + "-" + old_owner
        tgt = con.execute(
            "SELECT id,data,attrs_type,updated_at FROM attrs WHERE id=?", (tgt_id,)
        ).fetchone()
        tgt_dict = self._load_pc_dict(tgt["data"]) if tgt is not None else None
        old_ms = self._norm_ts(tgt["updated_at"]) if tgt is not None else 0

        if tgt is not None:
            res["old_len"] = len(bytes(tgt["data"] or b""))
        if src is not None:
            res["new_len"] = len(bytes(src["data"] or b""))
        res["old_ms"] = old_ms
        res["new_ms"] = new_ms

        if not src_dict and not tgt_dict:
            return res

        # 哪边的数据「更新」就作为同名字段值的优先来源
        newer_is_openqq = bool(new_ms > old_ms)
        newer_is_old = bool(old_ms > new_ms)

        # 计算旧QQ侧合并后的字典：
        #   * 旧QQ没有的字段 -> 从 OpenQQ 补过来
        #   * 同名字段 -> 谁更新用谁（旧QQ侧要跟随较新的值）
        merged_old = dict(tgt_dict or {})
        if src_dict:
            for k, v in src_dict.items():
                if k not in merged_old:
                    merged_old[k] = v
                    res["added_to_old"] += 1
                elif newer_is_openqq:
                    merged_old[k] = v

        # 计算 OpenQQ 侧合并后的字典，规则对称
        merged_new = dict(src_dict or {})
        if tgt_dict:
            for k, v in tgt_dict.items():
                if k not in merged_new:
                    merged_new[k] = v
                    res["added_to_new"] += 1
                elif newer_is_old:
                    merged_new[k] = v

        # 海豹的 updated_at 是【秒】，不要用毫秒，否则时间比较会完全错乱
        now_sec = int(time.time())

        # --- 写回旧QQ 侧 ---
        if merged_old:
            if tgt is None:
                con.execute(
                    "INSERT INTO attrs(id,data,attrs_type,binding_sheet_id,name,owner_id,"
                    "sheet_type,is_hidden,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (tgt_id, self._build_pc_data(merged_old),
                     (src["attrs_type"] if src is not None else ""), "", "", old_owner, "", 1,
                     int(time.time()), new_ms or now_sec),
                )
                res["action"] = "created_old"
            else:
                if not self._pc_equal(merged_old, tgt_dict):
                    con.execute(
                        "UPDATE attrs SET data=?, updated_at=? WHERE id=?",
                        (self._build_pc_data(merged_old), max(old_ms, new_ms) or now_sec, tgt["id"]),
                    )
                    if res["action"] == "none":
                        res["action"] = "merged_to_old"

        # --- 补齐 OpenQQ 侧（如果那边缺字段） ---
        if src is not None and merged_new:
            if not self._pc_equal(merged_new, src_dict):
                con.execute(
                    "UPDATE attrs SET data=?, updated_at=? WHERE id=?",
                    (self._build_pc_data(merged_new), max(old_ms, new_ms) or now_sec, src_id),
                )
                if res["action"] == "none":
                    res["action"] = "merged_to_new"

        if res["action"] == "none" and (res["added_to_old"] or res["added_to_new"]):
            res["action"] = "merged"
        return res

    # 兼容旧调用名（外部如果引用过）
    def push_pc_to_old(self, con, old_owner, old_group_id, current):
        return self.merge_pc_fields(con, old_owner, old_group_id, current)

    # ---------------------- 全量一次同步 ----------------------

    def sync_once(self, pair):
        """对一条同步关系跑一轮：log 双向增量 + 角色卡只增 + PC 回写。"""
        old = str(pair.get("old") or "").strip()
        old_group = str(pair.get("old_group") or "").strip()
        current = str(pair.get("current") or "").strip()
        target_group = str(pair.get("group") or "").strip()
        old_owner = "QQ:" + old if not old.startswith("QQ:") else old
        old_group_id = old_group if old_group.startswith("QQ-Group:") else "QQ-Group:" + old_group

        out = {"ok": False, "old": old, "old_group": old_group, "current": current,
               "group": target_group, "at": int(time.time())}
        db_backup = None
        logs_backup = None
        try:
            # 定时同步与 /verify-code 的绑定会改同一批 sqlite 文件，
            # 必须串行，否则出现 SQLITE_BUSY 或互相覆盖。
            with self._write_lock:
                if os.path.isfile(self.logs_path):
                    logs_backup = self._rolling_backup(self.logs_path, "incremental")
                con = _apply_text_factory(sqlite3.connect(self.logs_path, timeout=30))
                con.row_factory = sqlite3.Row
                con.execute("PRAGMA busy_timeout=30000")
                try:
                    out["logs"] = self.sync_logs_pair(con, old_group_id, target_group)
                finally:
                    con.close()

                db_backup = self.backup_db_before_bind(label="incremental")
                con = self.connect(self.db_path)
                try:
                    con.execute("BEGIN IMMEDIATE")
                    out["cards_added"] = self.sync_cards_add_only(con, old_owner, current)
                    out["pc"] = self.merge_pc_fields(con, old_owner, old_group_id, current)
                    con.commit()
                except Exception:
                    try:
                        con.rollback()
                    except Exception:
                        pass
                    raise
                finally:
                    con.close()
            out["ok"] = True
            out["db_backup"] = db_backup
            out["logs_backup"] = logs_backup
        except Exception as e:
            out["error"] = "%s: %s" % (type(e).__name__, e)
            self.log_error("sync_once failed for %s: %s" % (pair, out["error"]))
        return out

    def sync_all(self, only_due=False):
        """跑所有（或到期的）同步关系。"""
        cfg = self.load_sync_config()
        pairs = cfg.get("pairs")
        if not isinstance(pairs, list):
            return {"ok": True, "ran": 0, "results": []}
        now = int(time.time())
        results = []
        ran = 0
        for p in pairs:
            if not isinstance(p, dict) or not p.get("enabled", True):
                continue
            if only_due:
                interval = self._to_int(p.get("interval"), SYNC_DEFAULT_INTERVAL)
                last = self._to_int(p.get("last_run"), 0)
                if last and (now - last) < max(30, interval):
                    continue
            res = self.sync_once(p)
            p["last_run"] = now
            p["last_result"] = res
            results.append(res)
            ran += 1
        cfg["pairs"] = pairs
        self.save_sync_config(cfg)
        return {"ok": True, "ran": ran, "results": results}

    def bind(self, old, current, target_group, old_group):
        with self._write_lock:
            return self._bind_locked(old, current, target_group, old_group)

    def _bind_locked(self, old, current, target_group, old_group):
        old_owner = "QQ:" + old
        old_group_id = "QQ-Group:" + old_group
        # 海豹的 created_at / updated_at 是【秒】，保持一致
        now = int(time.time())
        backup_path = self.backup_db_before_bind()
        logs_backup_path = self.backup_logs_before_bind()
        con = None
        try:
            con = self.connect(self.db_path)
            con.execute("PRAGMA foreign_keys=ON")
            con.execute("BEGIN IMMEDIATE")

            # 同样用全表扫描：owner_id 上的索引可能损坏。
            char_rows = []
            for row in con.execute(
                "SELECT id,data,attrs_type,binding_sheet_id,name,owner_id,sheet_type,is_hidden,created_at,updated_at "
                "FROM attrs"
            ).fetchall():
                if str(row["owner_id"] or "") != old_owner:
                    continue
                char_rows.append(row)
            char_rows.sort(key=lambda r: self._to_int(r["updated_at"], 0), reverse=True)

            exact_id = old_group_id + "-" + old_owner
            # 只认属于旧 QQ 本人的群属性行（owner_id 是旧 QQ，或为空未被占用）。
            # 只按 id 匹配不安全：同一条 id 可能已被别的 OpenQQ 用户接管，
            # 那样会把别人的角色卡绑定搬过来，在群里显示成空卡。
            # 注意：这里用「全表扫描 + Python 过滤」而不是 SQL 的 WHERE id LIKE，
            # 因为海豹库的索引偶尔会损坏（integrity_check 报 wrong # of entries），
            # 一旦查询走了坏索引就会直接抛 database disk image is malformed，
            # 整个迁移失败。全表扫描只依赖表数据，坏索引也能正常工作。
            attr_rows = []
            for row in con.execute(
                "SELECT id,data,attrs_type,binding_sheet_id,name,owner_id,sheet_type,is_hidden,created_at,updated_at "
                "FROM attrs"
            ).fetchall():
                rid = str(row["id"] or "")
                rowner = str(row["owner_id"] or "")
                if rid != exact_id and not rid.startswith(exact_id):
                    continue
                # 只认属于旧 QQ 本人的行（owner_id 是旧 QQ，或为空未被占用）。
                # 只按 id 匹配不安全：同一条 id 可能已被别的 OpenQQ 用户接管，
                # 那样会把别人的角色卡绑定搬过来，在群里显示成空卡。
                if rowner not in ("", old_owner):
                    continue
                attr_rows.append(row)
            attr_rows.sort(key=lambda r: len(bytes(r["data"] or b"")), reverse=True)

            gp = con.execute(
                "SELECT name,last_command_time,auto_set_name_template,dice_side_num,created_at,updated_at "
                "FROM group_player_info WHERE user_id=? AND group_id=? ORDER BY updated_at DESC LIMIT 1",
                (old_owner, old_group_id),
            ).fetchone()

            copied_chars = []
            skipped_empty = []
            # 旧卡 id -> 新卡 id。群属性的 binding_sheet_id 必须跟着改，
            # 否则会指向旧 QQ 的卡、甚至别人的卡，表现就是“卡是空的”。
            card_id_map = {}
            for a in char_rows:
                raw = bytes(a["data"] or b"")
                if len(raw) <= 23:
                    skipped_empty.append(a["name"] or a["id"])
                    continue
                # IMPORTANT: create a new ID for the copied owner. Reusing the old
                # primary key would UPDATE/move the old card instead of copying it.
                old_id = str(a["id"])
                new_id = old_id
                # Prefer a deterministic suffix that remains stable across retries.
                if a["owner_id"] != current:
                    new_id = old_id + "-openqq-" + current.replace(":", "_")
                # Avoid collisions by checking first.
                if con.execute("SELECT 1 FROM attrs WHERE id=?", (new_id,)).fetchone():
                    # If the existing row already belongs to current owner, update it;
                    # otherwise create a unique ID.
                    owner_row = con.execute("SELECT owner_id FROM attrs WHERE id=?", (new_id,)).fetchone()
                    if owner_row and owner_row["owner_id"] != current:
                        base = new_id
                        n = 2
                        while con.execute("SELECT 1 FROM attrs WHERE id=?", (f"{base}-{n}",)).fetchone():
                            n += 1
                        new_id = f"{base}-{n}"
                card_id_map[old_id] = new_id
                con.execute(
                    "INSERT INTO attrs(id,data,attrs_type,binding_sheet_id,name,owner_id,sheet_type,is_hidden,created_at,updated_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?) "
                    "ON CONFLICT(id) DO UPDATE SET data=excluded.data,attrs_type=excluded.attrs_type,"
                    "binding_sheet_id=excluded.binding_sheet_id,name=excluded.name,owner_id=excluded.owner_id,"
                    "sheet_type=excluded.sheet_type,is_hidden=excluded.is_hidden,updated_at=excluded.updated_at",
                    (new_id, raw, a["attrs_type"], a["binding_sheet_id"], a["name"], current,
                     a["sheet_type"], a["is_hidden"], a["created_at"] or now, now),
                )
                copied_chars.append(a["name"] or new_id)

            copied_attrs = 0
            group_attr_action = "none"
            if attr_rows:
                a = attr_rows[0]
                target_id = target_group + "-" + current
                src_raw = bytes(a["data"] or b"")
                existing = con.execute(
                    "SELECT data FROM attrs WHERE id=?", (target_id,)
                ).fetchone()
                if existing is not None and len(bytes(existing["data"] or b"")) > 23:
                    # 目标群里已经有真实数据（当前人物卡状态），绝不覆盖，
                    # 否则本来好好的卡会被冲成空的。
                    group_attr_action = "kept_existing"
                else:
                    # 若这张卡本次被复制过，绑定跟着指向新副本；否则保留原绑定。
                    # 注意：不能因为「卡属于别的账号」就清空绑定 —— 海豹允许同群共用卡，
                    # 清空会让角色面板变成空的。
                    src_bind = (a["binding_sheet_id"] or "").strip()
                    new_bind = card_id_map.get(src_bind, src_bind)
                    if existing is not None:
                        con.execute(
                            "UPDATE attrs SET data=?,attrs_type=?,binding_sheet_id=?,name=?,owner_id=?,"
                            "sheet_type=?,is_hidden=?,updated_at=? WHERE id=?",
                            (src_raw, a["attrs_type"], new_bind, a["name"], current,
                             a["sheet_type"], a["is_hidden"], now, target_id),
                        )
                        group_attr_action = "replaced_empty"
                    else:
                        con.execute(
                            "INSERT INTO attrs(id,data,attrs_type,binding_sheet_id,name,owner_id,sheet_type,is_hidden,created_at,updated_at) "
                            "VALUES(?,?,?,?,?,?,?,?,?,?)",
                            (target_id, src_raw, a["attrs_type"], new_bind, a["name"], current,
                             a["sheet_type"], a["is_hidden"], a["created_at"] or now, now),
                        )
                        group_attr_action = "created"
                    copied_attrs = 1

            if gp:
                g = dict(gp)
                existing = con.execute(
                    "SELECT id FROM group_player_info WHERE user_id=? AND group_id=? ORDER BY id LIMIT 1",
                    (current, target_group),
                ).fetchone()
                if existing:
                    con.execute(
                        "UPDATE group_player_info SET name=?,last_command_time=?,auto_set_name_template=?,dice_side_num=?,updated_at=? WHERE id=?",
                        (g["name"], g["last_command_time"] or 0, g["auto_set_name_template"] or "",
                         g["dice_side_num"] or 100, now, existing["id"]),
                    )
                else:
                    con.execute(
                        "INSERT INTO group_player_info(name,user_id,last_command_time,auto_set_name_template,dice_side_num,created_at,updated_at,group_id) VALUES(?,?,?,?,?,?,?,?)",
                        (g["name"], current, g["last_command_time"] or 0, g["auto_set_name_template"] or "",
                         g["dice_side_num"] or 100, g["created_at"] or now, now, target_group),
                    )

            # Commit the main data first. Log migration is intentionally isolated
            # from this transaction: a malformed/corrupt data-logs.db must NOT
            # roll back character cards, group attributes, or player information.
            con.commit()

            log_result = {
                "log_count": 0,
                "log_item_count": 0,
                "log_skipped": 0,
                "log_failed": 0,
                "log_errors": [],
                "log_error": None,
            }
            try:
                log_result = self.migrate_logs(old_group_id, target_group)
            except Exception as e:
                # Keep the successful main-data migration and report the exact
                # log-side failure to the caller.
                log_result["log_error"] = f"{type(e).__name__}: {e}"
                self.log_error(f"Log migration failed for {old_group_id} -> {target_group}: {log_result['log_error']}")

            return {
                "ok": True,
                "characters": [{"name": n} for n in copied_chars],
                "character_count": len(copied_chars),
                "skipped_empty_characters": skipped_empty,
                "group_attr_count": copied_attrs,
                "group_attr_action": group_attr_action,
                "log_count": log_result.get("log_count", 0),
                "log_item_count": log_result.get("log_item_count", 0),
                "log_skipped": log_result.get("log_skipped", 0),
                "log_failed": log_result.get("log_failed", 0),
                "log_errors": log_result.get("log_errors", []),
                "log_error": log_result.get("log_error"),
                "backup": backup_path,
                "logs_backup": logs_backup_path,
            }
        except Exception:
            if con is not None:
                try: con.rollback()
                except Exception: pass
            raise
        finally:
            if con is not None:
                con.close()


class SyncWorker(threading.Thread):
    """后台定时器：按每条同步关系的 interval 跑增量同步。"""

    def __init__(self, bridge, tick=20):
        super().__init__(daemon=True)
        self.bridge = bridge
        self.tick = max(5, int(tick))
        self._stop = threading.Event()

    def stop(self):
        self._stop.set()

    def run(self):
        # 启动后稍等一会儿再跑第一轮，避免和启动流程抢资源
        if self._stop.wait(10):
            return
        while not self._stop.wait(self.tick):
            try:
                self.bridge.sync_all(only_due=True)
            except Exception as e:
                try:
                    self.bridge.log_error("sync worker tick failed: %s: %s" % (type(e).__name__, e))
                except Exception:
                    pass


class Handler(BaseHTTPRequestHandler):
    bridge = None
    token = ""

    def send_json(self, obj, status=200):
        raw = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_POST(self):
        try:
            u = urlparse(self.path)
            q = parse_qs(u.query)
            if not self.authorized(u.path, q):
                return
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length) if length else b"{}"
            try:
                body = json.loads(raw.decode("utf-8"))
            except Exception:
                raise RuntimeError("invalid JSON body")
            if u.path == "/set-email-config":
                self.send_json(self.bridge.set_email_config(body))
            elif u.path == "/email-test":
                self.send_json(self.bridge.send_test_email())
            else:
                self.send_json({"ok": False, "error": "not found"}, 404)
        except Exception as e:
            import traceback
            print("[ERROR] HTTP POST request failed:")
            traceback.print_exc()
            self.send_json({"ok": False, "error": f"{type(e).__name__}: {e}"}, 500)

    def do_GET(self):
        try:
            u = urlparse(self.path)
            q = parse_qs(u.query)
            if not self.authorized(u.path, q):
                return
            if u.path == "/health":
                self.send_json({"ok": True, "version": VERSION, "port": self.server.server_port,
                                "data_dir": self.bridge.data_dir})
            elif u.path == "/set-port":
                port = int(q.get("port", [""])[0])
                current = self.server.server_port
                saved = self.bridge.save_port(port)
                self.send_json({"ok": True, "port": saved, "old_port": current, "port_file": self.bridge.port_file})
                if saved != current:
                    # Return the response first, then let the CMD restart the bridge
                    # with the newly saved port.
                    import threading
                    threading.Timer(0.15, self.server.shutdown).start()
            elif u.path == "/sync-status":
                cfg = self.bridge.load_sync_config()
                pairs = self.bridge.list_sync_pairs()
                last = []
                for p in pairs:
                    last.append({
                        "old": p.get("old"), "old_group": p.get("old_group"),
                        "current": p.get("current"), "group": p.get("group"),
                        "enabled": bool(p.get("enabled", True)),
                        "interval": to_int(p.get("interval"), SYNC_DEFAULT_INTERVAL),
                        "last_run": to_int(p.get("last_run"), 0),
                        "last_result": p.get("last_result"),
                    })
                self.send_json({"ok": True, "count": len(pairs), "pairs": last})
            elif u.path == "/sync-now":
                old = q.get("old", [""])[0].strip().replace("QQ:", "")
                old_group = q.get("oldGroup", [""])[0].strip().replace("QQ-Group:", "")
                current = q.get("current", [""])[0].strip()
                target_group = q.get("group", [""])[0].strip()
                if old and old_group and current and target_group:
                    # 只跑这一条
                    pair = {"old": old, "old_group": old_group, "current": current, "group": target_group}
                    self.send_json(self.bridge.sync_once(pair))
                else:
                    # 不带参数时只返回汇总，避免把所有配对结果一次性塞进回复
                    res = self.bridge.sync_all(only_due=False)
                    self.send_json({"ok": bool(res.get("ok")),
                                    "ran": int(res.get("ran") or 0),
                                    "failed": sum(1 for r in res.get("results", []) if not r.get("ok"))})
            elif u.path == "/sync-enable":
                old = q.get("old", [""])[0].strip().replace("QQ:", "")
                old_group = q.get("oldGroup", [""])[0].strip().replace("QQ-Group:", "")
                current = q.get("current", [""])[0].strip()
                target_group = q.get("group", [""])[0].strip()
                on = q.get("on", ["1"])[0].strip() not in ("0", "false", "off", "no")
                if not all((old, old_group, current, target_group)):
                    raise RuntimeError("missing sync parameter")
                p = self.bridge.upsert_sync_pair(old, old_group, current, target_group, enabled=on)
                self.send_json({"ok": True, "enabled": bool(p.get("enabled", True))})
            elif u.path == "/sync-remove":
                old = q.get("old", [""])[0].strip().replace("QQ:", "")
                old_group = q.get("oldGroup", [""])[0].strip().replace("QQ-Group:", "")
                current = q.get("current", [""])[0].strip()
                target_group = q.get("group", [""])[0].strip()
                if not all((old, old_group, current, target_group)):
                    raise RuntimeError("missing sync parameter")
                left = self.bridge.remove_sync_pair(old, old_group, current, target_group)
                self.send_json({"ok": True, "remaining": left})
            elif u.path == "/lookup":
                old = q.get("old", [""])[0].strip().replace("QQ:", "")
                if not old:
                    raise RuntimeError("missing old")
                self.send_json(self.bridge.lookup(old))
            elif u.path == "/request-code":
                old = q.get("old", [""])[0].strip().replace("QQ:", "")
                current = q.get("current", [""])[0].strip()
                target_group = q.get("group", [""])[0].strip()
                old_group = q.get("oldGroup", [""])[0].strip().replace("QQ-Group:", "")
                if not all((old, current, target_group, old_group)):
                    raise RuntimeError("missing verification parameter")
                self.send_json(self.bridge.request_code(old, old_group, current, target_group))
            elif u.path == "/verify-code":
                old = q.get("old", [""])[0].strip().replace("QQ:", "")
                current = q.get("current", [""])[0].strip()
                target_group = q.get("group", [""])[0].strip()
                old_group = q.get("oldGroup", [""])[0].strip().replace("QQ-Group:", "")
                code = q.get("code", [""])[0].strip()
                if not all((old, current, target_group, old_group, code)):
                    raise RuntimeError("missing verification parameter")
                self.send_json(self.bridge.verify_code_and_bind(old, old_group, current, target_group, code))
            else:
                self.send_json({"ok": False, "error": "not found"}, 404)
        except Exception as e:
            import traceback
            print("[ERROR] HTTP request failed:")
            traceback.print_exc()
            self.send_json({"ok": False, "error": f"{type(e).__name__}: {e}"}, 500)

    def authorized(self, path, q):
        """可选共享令牌：仅当启动时设置了 --token / OPENQQ_BRIDGE_TOKEN 才校验。

        默认（Windows 单机使用）为空，行为与原版完全一致。
        /health 永远放行，方便 Docker HEALTHCHECK 和探活。
        """
        if not self.token or path == "/health":
            return True
        supplied = (q.get("token", [""])[0] or "").strip()
        if secrets.compare_digest(supplied, self.token):
            return True
        self.send_json({"ok": False, "error": "unauthorized"}, 401)
        return False

    def log_message(self, fmt, *args):
        print("[HTTP] " + (fmt % args))


def main():
    ap = argparse.ArgumentParser(description="OpenQQ QQ Sync Bridge v3.3")
    ap.add_argument("--port", type=int, default=None)
    ap.add_argument("--host", default=os.environ.get("OPENQQ_BRIDGE_HOST", "127.0.0.1"),
                    help="监听地址；Docker 里需要 0.0.0.0，默认 127.0.0.1 只允许本机访问")
    ap.add_argument("--data-dir", default="data/default")
    ap.add_argument("--token", default=os.environ.get("OPENQQ_BRIDGE_TOKEN", ""),
                    help="可选的共享访问令牌；留空则不做校验（仅建议在本机使用）")
    args = ap.parse_args()
    bridge = Bridge(args.data_dir)
    if args.port is None:
        args.port = bridge.read_saved_port()
    if not 1 <= args.port <= 65535:
        raise SystemExit("Invalid port")
    bridge.check()
    Handler.bridge = bridge
    Handler.token = str(args.token or "")
    print(f"OpenQQ QQ Sync Bridge v{VERSION}")
    print(f"Listening: {args.host}:{args.port}")
    print(f"Data dir: {bridge.data_dir}")
    print(f"Config dir: {root_dir()}")
    print("Token required: " + ("yes" if Handler.token else "no"))
    if os.environ.get("OPENQQ_BRIDGE_NO_SYNC", "").strip() in ("1", "true", "yes"):
        print("Incremental sync worker: disabled (OPENQQ_BRIDGE_NO_SYNC=1)")
    else:
        worker = SyncWorker(bridge, tick=int(os.environ.get("OPENQQ_BRIDGE_SYNC_TICK", "20") or 20))
        worker.start()
        print("Incremental sync worker: started")
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()

if __name__ == "__main__":
    main()
