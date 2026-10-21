"""Batch category and membership changes are atomic and limited to chosen rows."""
import os
import tempfile
import unittest
from unittest.mock import patch

import app as bill_app


class BatchOrganizeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_patch = patch.object(bill_app, "DB_PATH", os.path.join(self.temp.name, "test.db"))
        self.db_patch.start()
        bill_app.init_db()
        self.client = bill_app.app.test_client()
        self.a, self.b = [self.client.post("/api/ledgers", json={"name": name}).get_json()["item"]["id"]
                          for name in ("实习", "考研")]
        for index, (amount, direction) in enumerate(((100, "支出"), (30, "收入"), (25, "支出")), 1):
            response = self.client.post("/api/manual/add", json={
                "amount": str(amount), "direction": direction, "category": "其他",
                "counterparty": "同一家商户", "transaction_time": f"2026-10-{index:02d} 12:00:00",
            })
            self.assertEqual(response.status_code, 200)
        self.ids = [row["id"] for row in self.rows()]
        for tx_id in self.ids[:2]:
            self.client.post(f"/api/transactions/{tx_id}/ledgers", json={"ledger_ids": [0, self.a]})

    def tearDown(self):
        self.db_patch.stop()
        self.temp.cleanup()

    def rows(self):
        conn = bill_app.get_db()
        try:
            return [dict(row) for row in conn.execute(
                "SELECT id, amount, direction, unique_key, category, branch FROM transactions ORDER BY id"
            )]
        finally:
            conn.close()

    def memberships(self, tx_id):
        return self.client.get(f"/api/transactions/{tx_id}/ledgers").get_json()["ledger_ids"]

    def batch(self, **body):
        return self.client.post("/api/transactions/batch-organize", json=body)

    def test_group_members_can_be_classified_and_added_without_changing_other_rows(self):
        before = self.rows()
        created = self.client.post(f"/api/ledgers/{self.a}/display-groups", json={
            "tx_ids": self.ids[:2], "title": "实习交通",
        }).get_json()
        response = self.batch(ids=self.ids[:2], category="学习", ledger_mode="add", ledger_ids=[self.b])
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.get_json()["updated"], 2)
        after = self.rows()
        self.assertEqual([row["category"] for row in after], ["学习", "学习", "其他"])
        for old, new in zip(before, after):
            for key in ("id", "amount", "direction", "unique_key", "branch"):
                self.assertEqual(old[key], new[key])
        for tx_id in self.ids[:2]:
            self.assertEqual(self.memberships(tx_id), [0, self.a, self.b])
        self.assertEqual(self.memberships(self.ids[2]), [0])
        for ledger_id in (self.a, self.b):
            item = self.client.get(f"/api/ledgers/{ledger_id}/display").get_json()["items"][0]
            self.assertEqual(item["group_id"], created["group_id"])
            self.assertEqual(item["title"], "实习交通")
            self.assertEqual(item["amount"], 70)
        conn = bill_app.get_db()
        try:
            self.assertEqual(conn.execute("SELECT count(*) FROM merchant_rule_items").fetchone()[0], 0)
        finally:
            conn.close()

    def test_replace_overrides_category_rules_and_remove_keeps_other_memberships(self):
        self.client.put("/api/category-ledger-rules", json={
            "category": "学习", "ledger_ids": [self.b], "main_policy": "include",
        })
        response = self.batch(ids=self.ids[:2], category="学习", ledger_mode="replace", ledger_ids=[self.a])
        self.assertEqual(response.status_code, 200)
        for tx_id in self.ids[:2]:
            self.assertEqual(self.memberships(tx_id), [self.a])
        self.assertEqual(self.batch(ids=self.ids[:2], ledger_mode="add", ledger_ids=[0, self.b]).status_code, 200)
        self.assertEqual(self.batch(ids=self.ids[:2], ledger_mode="remove", ledger_ids=[self.a]).status_code, 200)
        for tx_id in self.ids[:2]:
            self.assertEqual(self.memberships(tx_id), [0, self.b])

    def test_replace_with_empty_list_moves_to_unassigned_and_can_be_reassigned(self):
        self.assertEqual(self.batch(ids=self.ids[:2], ledger_mode="replace", ledger_ids=[]).status_code, 200)
        for tx_id in self.ids[:2]:
            self.assertEqual(self.memberships(tx_id), [])
        items = self.client.get("/api/transactions?branch=__unassigned__").get_json()["items"]
        self.assertEqual({item["id"] for item in items}, set(self.ids[:2]))
        self.assertEqual(self.batch(ids=self.ids[:2], ledger_mode="add", ledger_ids=[self.b]).status_code, 200)
        for tx_id in self.ids[:2]:
            self.assertEqual(self.memberships(tx_id), [self.b])

    def test_invalid_batch_never_changes_any_selected_transaction(self):
        before = self.rows()
        memberships = [self.memberships(tx_id) for tx_id in self.ids]
        for payload in (
            {"ids": [self.ids[0], 999999], "category": "学习"},
            {"ids": self.ids, "category": "学习", "ledger_mode": "replace", "ledger_ids": [999999]},
            {"ids": self.ids, "category": "不存在的分类", "ledger_mode": "replace", "ledger_ids": [self.b]},
            {"ids": [True], "category": "学习"},
            {"ids": [1.2], "category": "学习"},
            {"ids": [2 ** 63], "category": "学习"},
            {"ids": [], "category": "学习"},
            {"ids": self.ids, "ledger_mode": "add", "ledger_ids": []},
            {"ids": self.ids, "ledger_mode": "remove", "ledger_ids": [False]},
            {"ids": self.ids},
            {"ids": self.ids, "ledger_mode": "wrong"},
        ):
            with self.subTest(payload=payload):
                self.assertIn(self.batch(**payload).status_code, (400, 404))
                self.assertEqual(self.rows(), before)
                self.assertEqual([self.memberships(tx_id) for tx_id in self.ids], memberships)

    def test_excluded_transaction_rejects_the_entire_batch(self):
        self.client.post(f"/api/transactions/{self.ids[1]}/count", json={"count_in_expense": False})
        before = self.rows()
        self.assertEqual(self.batch(ids=self.ids[:2], category="学习", ledger_mode="add", ledger_ids=[self.b]).status_code, 400)
        self.assertEqual(self.rows(), before)
        self.assertEqual(self.memberships(self.ids[0]), [0, self.a])

    def test_large_batch_and_duplicate_ids_count_distinct_transactions(self):
        conn = bill_app.get_db()
        try:
            conn.executemany("INSERT INTO transactions(source, direction, amount) VALUES ('manual', '支出', ?)",
                             [(1,)] * 600)
            conn.commit()
        finally:
            conn.close()
        ids = [row["id"] for row in self.rows()]
        response = self.batch(ids=ids + [str(ids[0])], category="学习", ledger_mode="add", ledger_ids=[self.b])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["updated"], len(ids))
        self.assertTrue(all(row["category"] == "学习" for row in self.rows()))
        self.assertEqual(self.batch(ids=[ids[0]] * 5001, category="其他").status_code, 400)

    def test_excluded_view_can_organize_without_restoring_or_changing_totals(self):
        tx_id = self.ids[1]
        self.client.post(f"/api/transactions/{tx_id}/count", json={
            "count_in_expense": False, "exclude_reason": "保留排除原因",
        })
        before = self.client.get("/api/summary?month=2026-10").get_json()
        response = self.batch(ids=[tx_id], category="学习", ledger_mode="add", ledger_ids=[self.b], scope="excluded")
        self.assertEqual(response.status_code, 200, response.get_json())
        row = next(item for item in self.client.get("/api/transactions?count_in_expense=0").get_json()["items"] if item["id"] == tx_id)
        self.assertEqual(row["category"], "学习")
        self.assertEqual(row["count_in_expense"], 0)
        self.assertEqual(row["exclude_reason"], "保留排除原因")
        self.assertEqual(row["ledger_ids"], [0, self.a, self.b])
        self.assertEqual(self.client.get("/api/summary?month=2026-10").get_json(), before)

    def test_excluded_scope_rejects_mixed_or_stale_selection_atomically(self):
        self.client.post(f"/api/transactions/{self.ids[0]}/count", json={"count_in_expense": False})
        before = self.rows()
        self.assertEqual(self.batch(ids=self.ids[:2], category="学习", scope="excluded").status_code, 400)
        self.assertEqual(self.rows(), before)
        self.assertEqual(self.batch(ids=self.ids, category="学习", scope="all").status_code, 400)
        self.assertEqual(self.rows(), before)


if __name__ == "__main__":
    unittest.main()
