# -*- coding: utf-8 -*-
"""构造一个「和海豹结构一致」的最小数据库，供测试使用。

只包含迁移逻辑真正会读写的表，字段与 SeaDice 的 data.db / data-logs.db 保持一致，
包括两个关键约束：
  - logs 上有 UNIQUE(name, group_id)   -> 撞名会报错，是历史 bug 的根源之一
  - group_player_info 上有 UNIQUE(user_id, group_id)
"""
import os, sqlite3

DATA_DB_DDL = """
CREATE TABLE `attrs` (`id` text,`data` blob,`attrs_type` text DEFAULT NULL,
  `binding_sheet_id` text DEFAULT "",`name` text,`owner_id` text,`sheet_type` text,
  `is_hidden` numeric,`created_at` integer,`updated_at` integer,PRIMARY KEY (`id`));
CREATE INDEX `idx_attrs_owner_id_id` ON `attrs`(`owner_id`);
CREATE TABLE `group_player_info` (`id` integer PRIMARY KEY AUTOINCREMENT,`name` text,
  `user_id` text,`last_command_time` integer,`auto_set_name_template` text,
  `dice_side_num` integer,`created_at` integer,`updated_at` integer,`group_id` text);
CREATE UNIQUE INDEX `idx_group_player_info_group_user` ON `group_player_info`(`user_id`,`group_id`);
"""

LOGS_DB_DDL = """
CREATE TABLE `logs` (`id` integer PRIMARY KEY AUTOINCREMENT,`name` text,`group_id` text,
  `created_at` integer,`updated_at` integer,`size` integer,`extra` text,
  `upload_url` text,`upload_time` integer);
CREATE UNIQUE INDEX `idx_log_group_id_name` ON `logs`(`name`,`group_id`);
CREATE TABLE `log_items` (`id` integer PRIMARY KEY AUTOINCREMENT,`log_id` integer,
  `group_id` text,`nickname` text,`im_userid` text,`time` integer,`message` text,
  `is_dice` numeric,`command_id` integer,`command_info` text,`raw_msg_id` text,
  `user_uniform_id` text,`removed` integer,`parent_id` integer);
CREATE INDEX `idx_log_items_log_id` ON `log_items`(`log_id`);
"""

# 一个「足够真实」的角色卡数据：> 23 字节才会被当作非空卡片复制。
CARD_BLOB = b"!sealdice/card/1\x00" + b"x" * 64


def make_data_db(path, with_cards=True):
    con = sqlite3.connect(path)
    con.executescript(DATA_DB_DDL)
    if with_cards:
        rows = [
            ("QQ-Group:1081354778-QQ:1721175359-罗京立", CARD_BLOB, "character", "", "罗京立", "QQ:1721175359", "character", 0, 1770984083, 1770984083),
            ("QQ-Group:1081354778-QQ:1721175359-藤本千夏", CARD_BLOB, "character", "", "藤本千夏", "QQ:1721175359", "character", 0, 1770984084, 1770984084),
            # 空卡片（data 很短）会被跳过，用来测试 skipped_empty_characters
            ("QQ-Group:1081354778-QQ:1721175359-空卡片", b"", "character", "", "空卡片", "QQ:1721175359", "character", 0, 1770984085, 1770984085),
        ]
        con.executemany("INSERT INTO attrs VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
        con.execute(
            "INSERT INTO group_player_info(name,user_id,last_command_time,auto_set_name_template,"
            "dice_side_num,created_at,updated_at,group_id) VALUES(?,?,?,?,?,?,?,?)",
            ("测试玩家", "QQ:1721175359", 1770984090, "", 100, 1770984083, 1770984090, "QQ-Group:1081354778"),
        )
    con.commit()
    con.close()
    return path


def make_logs_db(path, logs):
    """logs: list of dict(name=..., group_id=..., created_at=..., items=[(text, parent_index|None)])"""
    con = sqlite3.connect(path)
    con.executescript(LOGS_DB_DDL)
    for lg in logs:
        cur = con.execute(
            "INSERT INTO logs(name,group_id,created_at,updated_at,size,extra,upload_url,upload_time) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (lg["name"], lg["group_id"], lg.get("created_at", 0), lg.get("updated_at", 0),
             lg.get("size", 0), "", None, None),
        )
        log_id = cur.lastrowid
        index_map = {}
        for i, it in enumerate(lg.get("items", [])):
            text, parent_index = (it if isinstance(it, tuple) else (it, None))
            cur2 = con.execute(
                "INSERT INTO log_items(log_id,group_id,nickname,im_userid,time,message,is_dice,"
                "command_id,command_info,raw_msg_id,user_uniform_id,removed,parent_id) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (log_id, lg["group_id"], "某人", "QQ:1", 1770000000 + i, text, 0, 0, "",
                 "raw%d_%d" % (log_id, i), "u1", 0, index_map.get(parent_index)),
            )
            index_map[i] = cur2.lastrowid
    con.commit()
    con.close()
    return path
