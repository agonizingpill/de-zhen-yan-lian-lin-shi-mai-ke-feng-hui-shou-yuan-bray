from sqlalchemy import inspect, text

# 显式导入全部表定义，确保 metadata 已注册业务表（顺序覆盖外键依赖）。
from core import audit  # noqa: F401
from core.db import engine, metadata
from domain import channel, interventions, soundboard  # noqa: F401
from domain.venues import LEGACY_VENUE

# 以 code 为业务主键、需要替换为 (venue, code) 复合主键的表；audit_trail 不在其中。
CODE_PK_TABLES = (
    "microphone_points",
    "sound_windows",
    "feedback_findings",
    "channel_tickets",
    "patch_serial",
)

# 旧版单场地结构中的业务表：升级后全部加 venue，旧数据归入原场 LEGACY_VENUE。
LEGACY_TABLES = CODE_PK_TABLES + ("audit_trail",)

# 单场地时代的单列唯一约束列；升级后由 (venue, ...) 复合唯一约束取代。
LEGACY_UNIQUE = {
    "microphone_points": (("mic_tag",),),
    "sound_windows": (("point", "slot", "revision"),),
    "feedback_findings": (("focus_window",), ("compute_token",)),
    "channel_tickets": (("finding",), ("reline_window",)),
}

# 升级后要补建的复合唯一约束（名称与新表定义保持一致）。
NEW_UNIQUE = {
    "microphone_points": ["uq_points_venue_mic_tag"],
    "sound_windows": ["uq_windows_venue_point_slot_revision"],
    "feedback_findings": ["uq_findings_venue_window", "uq_findings_venue_token"],
    "channel_tickets": ["uq_tickets_venue_finding", "uq_tickets_venue_reline"],
}

# 场地合法性 CHECK，按表显式补建（create_all 不会为已存在的表补约束）。
VENUE_CHECK = "chk_venue_legit"

# 升级后要补建的复合外键（名称与新表定义保持一致）。
NEW_FOREIGN_KEYS = {
    "sound_windows": [
        ("fk_windows_point", "(`venue`, `point`)",
         "`microphone_points` (`venue`, `code`)"),
    ],
    "feedback_findings": [
        ("fk_findings_window", "(`venue`, `focus_window`)",
         "`sound_windows` (`venue`, `code`)"),
    ],
    "channel_tickets": [
        ("fk_tickets_point", "(`venue`, `point`)",
         "`microphone_points` (`venue`, `code`)"),
        ("fk_tickets_finding", "(`venue`, `finding`)",
         "`feedback_findings` (`venue`, `code`)"),
        ("fk_tickets_reline", "(`venue`, `reline_window`)",
         "`sound_windows` (`venue`, `code`)"),
    ],
}

# 各子表在单场地时代持有的旧外键，升级时删除并由复合外键取代。
LEGACY_FK_TABLES = ("sound_windows", "feedback_findings", "channel_tickets")


def _inspector(conn):
    # 不缓存：改名/建表后反射结果必须刷新，避免把 _old 表误判为新表已存在。
    return inspect(conn.bind if conn.bind is not None else conn)


def _columns(conn, table):
    return {col["name"] for col in inspect(conn).get_columns(table)}


def _has_table(conn, table):
    return inspect(conn).has_table(table)


def _needs_upgrade(conn):
    return any(_has_table(conn, table) and "venue" not in _columns(conn, table)
               for table in LEGACY_TABLES)


def _drop_legacy_unique_keys(conn):
    inspector = _inspector(conn)
    for table, groups in LEGACY_UNIQUE.items():
        if not _has_table(conn, table) or "venue" not in _columns(conn, table):
            continue
        targets = {tuple(group) for group in groups}
        for constraint in inspector.get_unique_constraints(table):
            if constraint["name"] and tuple(constraint["column_names"]) in targets:
                conn.execute(text(f"ALTER TABLE `{table}` DROP INDEX `{constraint['name']}`"))


def _existing_unique_names(conn, table):
    return {item["name"] for item in _inspector(conn).get_unique_constraints(table)}


def _existing_check_names(conn, table):
    return {item["name"] for item in _inspector(conn).get_check_constraints(table)}


def _add_new_constraints(conn):
    for table, names in NEW_UNIQUE.items():
        if not _has_table(conn, table) or "venue" not in _columns(conn, table):
            continue
        present = _existing_unique_names(conn, table)
        for name in names:
            if name in present:
                continue
            conn.execute(text(f"ALTER TABLE `{table}` ADD CONSTRAINT `{name}` "
                              f"{_unique_ddl(table, name)}"))
        if VENUE_CHECK not in _existing_check_names(conn, table):
            conn.execute(text(
                f"ALTER TABLE `{table}` ADD CONSTRAINT `{VENUE_CHECK}` "
                f"CHECK (`venue` IN ('{LEGACY_VENUE}','SITE-B'))"))


def _unique_ddl(table, name):
    ddl = {
        ("microphone_points", "uq_points_venue_mic_tag"):
            "UNIQUE (`venue`, `mic_tag`)",
        ("sound_windows", "uq_windows_venue_point_slot_revision"):
            "UNIQUE (`venue`, `point`, `slot`, `revision`)",
        ("feedback_findings", "uq_findings_venue_window"):
            "UNIQUE (`venue`, `focus_window`)",
        ("feedback_findings", "uq_findings_venue_token"):
            "UNIQUE (`venue`, `compute_token`)",
        ("channel_tickets", "uq_tickets_venue_finding"):
            "UNIQUE (`venue`, `finding`)",
        ("channel_tickets", "uq_tickets_venue_reline"):
            "UNIQUE (`venue`, `reline_window`)",
    }
    return ddl[(table, name)]


def _existing_fk_names(conn, table):
    return {item["name"] for item in inspect(conn).get_foreign_keys(table)}


def _rebuild_foreign_keys(conn):
    for table in LEGACY_FK_TABLES:
        if not _has_table(conn, table) or "venue" not in _columns(conn, table):
            continue
        # 删除单场地时代残留的旧外键（父表主键已变为复合键，旧单列引用已失效）。
        for fk in inspect(conn).get_foreign_keys(table):
            if fk["name"]:
                conn.execute(text(
                    f"ALTER TABLE `{table}` DROP FOREIGN KEY `{fk['name']}`"))
        present = _existing_fk_names(conn, table)
        for name, columns, reference in NEW_FOREIGN_KEYS[table]:
            if name in present:
                continue
            conn.execute(text(
                f"ALTER TABLE `{table}` ADD CONSTRAINT `{name}` "
                f"FOREIGN KEY {columns} REFERENCES {reference}"))


def _mysql_upgrade(conn):
    # 先停用外键检查，便于把单列主键替换为 (venue, code) 复合主键。
    conn.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
    try:
        for table in LEGACY_TABLES:
            if not _has_table(conn, table) or "venue" in _columns(conn, table):
                continue
            # 旧数据归入原场；DEFAULT 仅用于回填，随后去掉，避免后续误写。
            add_column = (
                f"ALTER TABLE `{table}` ADD COLUMN `venue` VARCHAR(12) "
                f"NOT NULL DEFAULT '{LEGACY_VENUE}' FIRST")
            if table in CODE_PK_TABLES:
                # 业务表把单列主键替换为 (venue, code) 复合主键；audit_trail 保留自增 id。
                add_column += ", DROP PRIMARY KEY, ADD PRIMARY KEY (`venue`, `code`)"
            conn.execute(text(add_column))
        # 旧的单列唯一约束会挡住两场同号数据，先删除。
        _drop_legacy_unique_keys(conn)
        # 旧单列外键随父表主键变更而失效，重建为带 venue 的复合外键。
        _rebuild_foreign_keys(conn)
        # 显式补建复合唯一约束与场地 CHECK（create_all 不会改已存在的表）。
        _add_new_constraints(conn)
    finally:
        conn.execute(text("SET FOREIGN_KEY_CHECKS = 1"))
    metadata.create_all(conn)


def _sqlite_rebuild(conn):
    """SQLite 不能改主键：按新结构建表、搬数据、替换旧表。"""
    # 先停用外键，避免改名/重建期间触发引用检查。
    conn.execute(text("PRAGMA foreign_keys=OFF"))
    try:
        for table in LEGACY_TABLES:
            if not _has_table(conn, table) or "venue" in _columns(conn, table):
                continue
            old_cols = [col["name"] for col in inspect(conn).get_columns(table)]
            conn.execute(text(
                f"ALTER TABLE {table} RENAME TO {table}_old"))
            # 目标表已被改名移走；用同一连接建表，确保看到本事务未提交的改名。
            metadata.create_all(conn, tables=[metadata.tables[table]], checkfirst=False)
            col_list = ", ".join(["venue"] + old_cols)
            conn.execute(text(
                f"INSERT INTO {table} ({col_list}) "
                f"SELECT '{LEGACY_VENUE}', {', '.join(old_cols)} FROM {table}_old"))
            conn.execute(text(f"DROP TABLE {table}_old"))
    finally:
        conn.execute(text("PRAGMA foreign_keys=ON"))
    metadata.create_all(conn)


def migrate():
    """幂等迁移：已是多场地结构时只补建新表；旧库只升级一次，重跑不重复入档。"""
    with engine.begin() as conn:
        if not _needs_upgrade(conn):
            metadata.create_all(conn)
            return
        if engine.dialect.name == "mysql":
            _mysql_upgrade(conn)
        elif engine.dialect.name == "sqlite":
            _sqlite_rebuild(conn)
        else:  # pragma: no cover - 项目仅交付 MySQL
            raise RuntimeError(f"不支持的数据库方言：{engine.dialect.name}")
        metadata.create_all(conn)
