# -*- coding: utf-8 -*-
"""Offline v2 policy tests; all region IDs below are synthetic."""
import json
import tempfile
import unittest
from pathlib import Path
from app_v5.item_area_policy import (
    SCHEMA_V2, load_allowlist, classify_area, configured_label,
    ALLOWED, UNKNOWN, OUTSIDE,
)


class HierarchicalAreaTests(unittest.TestCase):
    def policy(self, rows=None):
        rows = rows if rows is not None else [
            dict(key="test_metro_a", city="서울특별시", borough="동작구",
                 district="가상동", region_id="900001"),
            dict(key="test_metro_b", city="서울특별시", borough="관악구",
                 district="가상동", region_id="900002"),
            dict(key="test_rural_a", city="아산시", borough=None,
                 district="가상면", region_id="900003"),
        ]
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "policy.json"
            p.write_text(json.dumps({"schema": SCHEMA_V2,
                                     "allowed_areas": rows}), encoding="utf-8")
            return load_allowlist(p)

    def test_hierarchy_and_exact_pinned_id_required(self):
        policy = self.policy()
        for row in policy:
            source = dict(id=row["region_id"], city=row["city"],
                          name=row["district"])
            if row["borough"]:
                source["borough"] = row["borough"]
            with self.subTest(key=row["key"]):
                self.assertEqual(classify_area(source, policy)["area_key"], row["key"])
                self.assertEqual(classify_area(
                    {k: v for k, v in source.items() if k != "id"}, policy)["status"],
                    UNKNOWN)
                self.assertEqual(classify_area({"id": row["region_id"]}, policy)["status"],
                                 UNKNOWN)
                self.assertFalse(classify_area(source, policy)["authorizes_listings"])
        self.assertEqual(configured_label("test_metro_a", policy),
                         "서울특별시 동작구 가상동")

    def test_conflicting_or_missing_borough_held(self):
        policy = self.policy()
        base = dict(id="900001", city="서울특별시", name="가상동")
        for extra in ({}, {"borough": "관악구"},
                      {"borough": "동작구", "boroughName": "관악구"},
                      {"borough": []}, {"borough": "동작구", "id": "900099"},
                      {"borough": "동작구", "city": "아산시"}):
            with self.subTest(extra=extra):
                self.assertEqual(classify_area(dict(base, **extra), policy)["status"], UNKNOWN)

    def test_outside_requires_complete_explicit_location(self):
        policy = self.policy()
        outside = dict(id="900099", city="서울특별시",
                       borough="서초구", name="가상동")
        self.assertEqual(classify_area(outside, policy)["status"], OUTSIDE)
        del outside["borough"]
        self.assertEqual(classify_area(outside, policy)["status"], UNKNOWN)

    def test_reject_unpinned_duplicate_or_broad_policy(self):
        row = dict(key="test_metro_a", city="서울특별시", borough="동작구",
                   district="가상동", region_id="900001")
        for changes in ({"region_id": None}, {"borough": None},
                        {"borough": "동작*"}, {"city": "서울"},
                        {"district": "가상*"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.policy([dict(row, **changes)])
        with self.assertRaises(ValueError):
            self.policy([row, dict(row, key="other_key", region_id="900002")])
        with self.assertRaises(ValueError):
            self.policy([row, dict(row, key="other_key", borough="관악구")])


if __name__ == "__main__":
    unittest.main()
