"""Nested display groups preserve identity and never count a leaf twice."""

import os
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import app as bill_app


class NestedGroupTests(unittest.TestCase):
    def setUp(self):
        self.sandbox = tempfile.TemporaryDirectory()
        self.db_patch = patch.object(bill_app, "DB_PATH", os.path.join(self.sandbox.name, "test.db"))
        self.db_patch.start()
        bill_app.init_db()
        self.client = bill_app.app.test_client()
        self.ledger = self.client.post("/api/ledgers", json={"name": "工资账本"}).get_json()["item"]["id"]

    def tearDown(self):
        self.db_patch.stop()
        self.sandbox.cleanup()

    def add(self, amount="1500", direction="收入", month="09"):
        response = self.client.post("/api/manual/add", json={
            "branch": "工资账本", "amount": amount, "direction": direction,
            "category": "其他", "counterparty": "北京即墨网络科技有限公司",
            "transaction_time": f"2026-{month}-19 22:02:54",
        })
        self.assertEqual(response.status_code, 200, response.get_json())
        conn = bill_app.get_db()
        try:
            return conn.execute("SELECT MAX(id) FROM transactions").fetchone()[0]
        finally:
            conn.close()

    def create(self, items, title="组合", parent=None, ledger=None):
        response = self.client.post(f"/api/ledgers/{ledger or self.ledger}/display-groups", json={
            "item_ids": items, "title": title, "parent_group_id": parent,
        })
        self.assertEqual(response.status_code, 200, response.get_json())
        return response.get_json()["group_id"]

    def display(self, ledger=None, month=None):
        response = self.client.get(f"/api/ledgers/{ledger or self.ledger}/display" +
                                   (f"?month=2026-{month}" if month else ""))
        self.assertEqual(response.status_code, 200)
        return response.get_json()

    def snapshot(self):
        conn = bill_app.get_db()
        try:
            return {table: [tuple(row) for row in conn.execute(f"SELECT * FROM {table}")]
                    for table in ("transactions", "ledger_display_groups", "ledger_display_group_items",
                                  "effective_transaction_ledgers")}
        finally:
            conn.close()

    def move(self, target, items, ledger=None):
        response = self.client.post(f"/api/ledgers/{ledger or self.ledger}/display-groups/{target}/items",
                                    json={"item_ids": items})
        self.assertEqual(response.status_code, 200, response.get_json())
        return response.get_json()

    def test_add_sibling_raw_entry_to_existing_child_without_splitting(self):
        a, b, c, d = [self.add() for _ in range(4)]
        outer = self.create([a, b, c, d], "anta支出")
        target = self.create([a, b], "anta打车", outer)
        sibling = self.create([d], "anta体检", outer)
        source = self.snapshot()["transactions"]
        self.move(target, [c])
        root = self.display()["items"][0]
        self.assertEqual((root["group_id"], root["title"], root["amount"]), (outer, "anta支出", 6000))
        self.assertEqual([(item["group_id"], item["title"], len(item["members"])) for item in root["children"]],
                         [(target, "anta打车", 3), (sibling, "anta体检", 1)])
        self.assertEqual(self.snapshot()["transactions"], source)

    def test_add_external_entry_updates_all_ancestors_and_shared_ledgers(self):
        a, b, c = [self.add() for _ in range(3)]
        outer = self.create([a, b], "anta支出")
        target = self.create([a], "anta打车", outer)
        other = self.client.post("/api/ledgers", json={"name": "共享账本"}).get_json()["item"]["id"]
        self.assertEqual(self.client.post(f"/api/transactions/{c}/ledgers", json={
            "ledger_ids": [self.ledger, other],
        }).status_code, 200)
        self.assertEqual(self.client.post(f"/api/transactions/{c}/ledger-amount", json={
            "ledger_id": other, "amount": "500",
        }).status_code, 200)
        result = self.move(target, [c])
        self.assertEqual(result["ancestor_group_ids"], [target, outer])
        self.assertEqual(next(item for item in result["affected_ledgers"] if item["id"] == other)["added"], 2)
        for ledger, amount in ((self.ledger, 4500), (other, 3500)):
            root = self.display(ledger)["items"][0]
            self.assertEqual((root["group_id"], root["amount"], len(root["members"])), (outer, amount, 3))
            nested = next(item for item in root["children"] if item["type"] == "group")
            self.assertEqual((nested["group_id"], len(nested["members"])), (target, 2))

    def test_move_entire_group_retains_descendants_and_removes_empty_source(self):
        a, b, c, d = [self.add() for _ in range(4)]
        destination = self.create([a, b], "anta打车")
        source = self.create([c, d], "临时外层")
        inner = self.create([c, d], "七月打车", source)
        deeper = self.create([c], "第一周", inner)
        result = self.move(destination, [f"g-{inner}"])
        self.assertEqual(result["removed_empty_group_ids"], [source])
        root = self.display()["items"][0]
        nested = next(item for item in root["children"] if item["type"] == "group")
        self.assertEqual((root["group_id"], root["title"], root["amount"]), (destination, "anta打车", 6000))
        self.assertEqual((nested["group_id"], nested["title"], nested["parent_group_id"]),
                         (inner, "七月打车", destination))
        self.assertEqual(nested["children"][0]["group_id"], deeper)
        bill_app.init_db()
        self.assertEqual(self.display()["items"][0], root)

    def test_move_multiple_levels_keeps_net_and_no_orphans(self):
        a, b, c, d, e = [self.add() for _ in range(5)]
        destination = self.create([a, b], "目标")
        source = self.create([c, d], "移空后删除")
        child = self.create([c], "原子组合", source)
        self.move(destination, [f"g-{child}", d, e])
        root = self.display()["items"][0]
        self.assertEqual((root["amount"], len(root["members"])), (7500, 5))
        self.assertEqual(self.display()["net"], 7500)
        group_rows = self.snapshot()["ledger_display_groups"]
        self.assertEqual({row[0] for row in group_rows}, {destination, child})
        self.assertEqual(next(item for item in root["children"] if item["type"] == "group")["group_id"], child)

    def test_invalid_moves_rollback_groups_and_memberships(self):
        a, b, c, d = [self.add() for _ in range(4)]
        outer = self.create([a, b, c], "外层")
        child = self.create([a, b], "子组合", outer)
        before = self.snapshot()
        invalid = [
            (child, [f"g-{child}"]), (child, [f"g-{outer}"]),
            (child, [a]), (child, [c, c]), (child, [99999]),
            (child, [f"g-{outer}", a]), (outer, [f"g-{child}", a]),
            (99999, [d]), (child, [True]), (child, ["g-99999"]),
        ]
        for target, items in invalid:
            with self.subTest(target=target, items=items):
                response = self.client.post(f"/api/ledgers/{self.ledger}/display-groups/{target}/items", json={"item_ids": items})
                self.assertIn(response.status_code, (400, 404, 409), response.get_json())
                self.assertEqual(self.snapshot(), before)

    def test_move_rejects_unavailable_target_and_excluded_source(self):
        a, b, c = [self.add() for _ in range(3)]
        target = self.create([a, b])
        self.client.post(f"/api/transactions/{c}/count", json={"count_in_expense": False})
        before = self.snapshot()
        response = self.client.post(f"/api/ledgers/{self.ledger}/display-groups/{target}/items", json={"item_ids": [c]})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.snapshot(), before)
        other = self.client.post("/api/ledgers", json={"name": "无成员账本"}).get_json()["item"]["id"]
        self.client.post(f"/api/transactions/{c}/count", json={"count_in_expense": True})
        self.client.post(f"/api/transactions/{c}/ledgers", json={"ledger_ids": [other]})
        before = self.snapshot()
        response = self.client.post(f"/api/ledgers/{other}/display-groups/{target}/items", json={"item_ids": [c]})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.snapshot(), before)

    def test_move_checks_ancestor_capacity_before_adding_ledger_memberships(self):
        ids = [self.add("1") for _ in range(201)]
        outer = self.create(ids[:200])
        child = self.create([ids[0]], "可添加但外层已满", outer)
        before = self.snapshot()
        response = self.client.post(f"/api/ledgers/{self.ledger}/display-groups/{child}/items", json={"item_ids": [ids[-1]]})
        self.assertEqual(response.status_code, 409)
        self.assertIn("200", response.get_json()["error"])
        self.assertEqual(self.snapshot(), before)

    def test_move_checks_depth_of_moved_subtree(self):
        a, b, c, d = [self.add() for _ in range(4)]
        parent = self.create([a, b])
        for _ in range(bill_app.MAX_DISPLAY_GROUP_DEPTH - 1):
            parent = self.create([a], parent=parent)
        moving = self.create([c, d], "不能成为第33层")
        before = self.snapshot()
        response = self.client.post(f"/api/ledgers/{self.ledger}/display-groups/{parent}/items", json={"item_ids": [f"g-{moving}"]})
        self.assertEqual(response.status_code, 409)
        self.assertIn("32", response.get_json()["error"])
        self.assertEqual(self.snapshot(), before)

    def test_salary_subgroups_and_single_entry_keep_totals_and_source_keys(self):
        ids = [self.add(), self.add("1900", "支出"), self.add("3500"), self.add()]
        before = self.snapshot()["transactions"]
        outer = self.create(ids, "即墨工资")
        july = self.create(ids[:2], "七月工资", outer)
        august = self.create([ids[2]], "八月工资", outer)
        root = self.display()["items"][0]
        self.assertEqual((root["title"], root["amount"], root["direction"]), ("即墨工资", 4600, "收入"))
        self.assertEqual([(child["id"], child["amount"]) for child in root["children"]],
                         [(f"g-{july}", 400), (f"g-{august}", 3500), (ids[3], 1500)])
        self.assertEqual(self.display()["net"], 4600)
        self.assertEqual(self.snapshot()["transactions"], before)
        bill_app.init_db()
        self.assertEqual(self.display()["items"][0], root)

    def test_cross_ledger_nested_names_and_amount_overrides(self):
        a, b, c = self.add(), self.add("100", "支出"), self.add("3500")
        other = self.client.post("/api/ledgers", json={"name": "另一账本"}).get_json()["item"]["id"]
        self.assertEqual(self.client.post(f"/api/transactions/{a}/ledgers", json={
            "ledger_ids": [self.ledger, other],
        }).status_code, 200)
        first = self.create([a, b], "七月工资")
        outer = self.create([f"g-{first}", c], "即墨工资")
        self.assertEqual(self.client.post(f"/api/transactions/{a}/ledger-amount", json={
            "ledger_id": other, "amount": "1000",
        }).status_code, 200)
        self.assertEqual(self.client.patch(f"/api/ledger-display-groups/{first}", json={
            "title": "七月工资（已核对）",
        }).status_code, 200)
        for ledger, amount in ((self.ledger, 4900), (other, 4400)):
            root = self.display(ledger)["items"][0]
            self.assertEqual((root["group_id"], root["amount"]), (outer, amount))
            self.assertEqual(root["children"][0]["title"], "七月工资（已核对）")
        self.assertEqual(self.client.delete(f"/api/ledger-display-groups/{outer}").status_code, 200)
        for ledger in (self.ledger, other):
            items = self.display(ledger)["items"]
            self.assertEqual(len(items), 2)
            self.assertEqual(next(item for item in items if item["type"] == "group")["group_id"], first)

    def test_monthly_view_keeps_complete_children_and_all_time_parent(self):
        a, b, c = self.add(month="07"), self.add(month="07"), self.add(month="08")
        outer = self.create([a, b, c], "即墨工资")
        july = self.create([a, b], "七月工资", outer)
        july_view = self.display(month="07")
        self.assertEqual(len(july_view["items"]), 1)
        self.assertEqual(july_view["items"][0]["group_id"], july)
        self.assertEqual(july_view["items"][0]["parent_group_id"], outer)
        self.assertEqual(july_view["net"], 3000)
        self.assertEqual(self.display(month="08")["items"][0]["parent_group_id"], outer)
        self.assertEqual(self.display()["items"][0]["group_id"], outer)

    def test_invalid_cross_level_or_overlapping_requests_are_atomic(self):
        a, b, c, d = [self.add() for _ in range(4)]
        outer = self.create([a, b, c], "即墨工资")
        child = self.create([a, b], "七月工资", outer)
        invalid = [
            {"item_ids": [f"g-{outer}", f"g-{child}"]},
            {"item_ids": [f"g-{outer}", a]},
            {"item_ids": [a, c], "parent_group_id": outer},
            {"item_ids": [f"g-{child}", d], "parent_group_id": outer},
            {"item_ids": [f"g-{outer}"], "parent_group_id": child},
            {"item_ids": [a], "parent_group_id": 99999},
            {"item_ids": [c], "parent_group_id": outer, "title": "字" * 81},
        ]
        before = self.snapshot()
        for body in invalid:
            with self.subTest(body=body):
                response = self.client.post(f"/api/ledgers/{self.ledger}/display-groups", json=body)
                self.assertIn(response.status_code, (400, 404, 409), response.get_json())
                self.assertEqual(self.snapshot(), before)

    def test_excluding_leaf_preserves_unaffected_sibling_group(self):
        a, b, c, d = [self.add() for _ in range(4)]
        outer = self.create([a, b, c, d], "即墨工资")
        july = self.create([a, b], "七月工资", outer)
        august = self.create([c, d], "八月工资", outer)
        self.assertEqual(self.client.post(f"/api/transactions/{a}/count", json={
            "count_in_expense": False,
        }).status_code, 200)
        items = self.display()["items"]
        self.assertEqual({item["id"] for item in items}, {b, f"g-{august}"})
        group = next(item for item in items if item["type"] == "group")
        self.assertIsNone(group["parent_group_id"])
        self.assertEqual(group["title"], "八月工资")
        conn = bill_app.get_db()
        try:
            self.assertEqual([row[0] for row in conn.execute("SELECT id FROM ledger_display_groups")], [august])
        finally:
            conn.close()

    def test_depth_limit_rejects_one_more_layer_without_mutation(self):
        a, b = self.add(), self.add()
        current = self.create([a, b])
        for depth in range(1, bill_app.MAX_DISPLAY_GROUP_DEPTH):
            current = self.create([a], f"第{depth + 1}层", current)
        before = self.snapshot()
        response = self.client.post(f"/api/ledgers/{self.ledger}/display-groups", json={
            "item_ids": [a], "parent_group_id": current,
        })
        self.assertEqual(response.status_code, 400)
        self.assertIn("32", response.get_json()["error"])
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.display()["net"], 3000)

    def test_old_flat_schema_migration_backs_up_and_preserves_identity(self):
        a, b = self.add(), self.add()
        outer = self.create([a, b], "旧版即墨工资")
        source = self.snapshot()["transactions"]
        conn = bill_app.get_db()
        try:
            conn.execute("DELETE FROM app_migrations WHERE name='nested_display_groups_v1'")
            conn.execute("DROP INDEX idx_display_group_parent")
            conn.execute("ALTER TABLE ledger_display_groups DROP COLUMN parent_group_id")
            conn.execute("ALTER TABLE ledger_display_group_items RENAME TO group_items_new")
            conn.execute("""CREATE TABLE ledger_display_group_items (
                group_id INTEGER NOT NULL, ledger_id INTEGER NOT NULL, tx_id INTEGER NOT NULL,
                PRIMARY KEY(group_id, tx_id), UNIQUE(ledger_id, tx_id))""")
            conn.execute("INSERT INTO ledger_display_group_items SELECT * FROM group_items_new")
            conn.execute("DROP TABLE group_items_new")
            conn.commit()
        finally:
            conn.close()
        bill_app.init_db()
        root = self.display()["items"][0]
        self.assertEqual((root["group_id"], root["title"], root["parent_group_id"]), (outer, "旧版即墨工资", None))
        backups = list(Path(self.sandbox.name).glob("bill_data_before_nested_groups_*.db"))
        self.assertEqual(len(backups), 1)
        with closing(sqlite3.connect(str(backups[0]))) as backup:
            self.assertNotIn("parent_group_id", [row[1] for row in backup.execute("PRAGMA table_info(ledger_display_groups)")])
            self.assertEqual(backup.execute("SELECT title FROM ledger_display_groups").fetchone()[0], "旧版即墨工资")
        child = self.create([a], "七月工资", outer)
        bill_app.init_db()
        self.assertEqual(self.display()["items"][0]["children"][0]["group_id"], child)
        self.assertEqual(self.snapshot()["transactions"], source)
        self.assertEqual(list(Path(self.sandbox.name).glob("bill_data_before_nested_groups_*.db")), backups)


if __name__ == "__main__":
    unittest.main()
