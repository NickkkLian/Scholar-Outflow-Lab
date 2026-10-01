"""scripts/venues.py builds the venue board from the OpenAlex API (network), so its labels are tested directly:
the field labels it stores are English, match compute.py's, and keep the field picker's order."""
import importlib.util
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load(name):
    spec = importlib.util.spec_from_file_location(f"{name}_under_test", os.path.join(ROOT, "scripts", f"{name}.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestVenueLabels(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.v, cls.c = load("venues"), load("compute")

    def test_same_english_labels_as_compute(self):
        self.assertEqual(self.v.FIELD_LABEL, self.c.FIELD_LABEL)
        for label in list(self.v.FIELD_LABEL.values()) + self.v.FIELD_ORDER:
            self.assertRegex(label, r"^[\x20-\x7e]+$")

    def test_field_order_keeps_the_picker_order(self):
        self.assertEqual(sorted(self.v.FIELD_ORDER), sorted(self.v.FIELD_LABEL.values()))
        shuffled = sorted(self.v.FIELD_ORDER, key=len)
        self.assertEqual(self.v.field_order(shuffled), self.v.FIELD_ORDER)
        self.assertEqual(self.v.field_order(["Zoology", "Medicine"]), ["Medicine", "Zoology"])   # unknown goes last

    def test_a_venue_without_a_field_is_filed_under_other(self):
        by_field = self.v.retier([{"field": "", "h": 3}, {"field": "Medicine", "h": 9}])
        self.assertEqual(sorted(by_field), ["Medicine", "Other"])


if __name__ == "__main__":
    unittest.main()
