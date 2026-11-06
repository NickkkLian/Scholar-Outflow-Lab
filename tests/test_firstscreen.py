"""The first-screen chart must render the actual data, its whole, and its limits."""
import json
from pathlib import Path
import re
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


def render(lang="en", changed=False):
    result = subprocess.run(["node", str(ROOT / "tests/render_firstscreen.mjs"), lang,
                             "changed" if changed else "published"], capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


class TestFirstScreen(unittest.TestCase):
    def test_one_chart_with_four_origins_on_a_common_percent_axis(self):
        page = render()
        chart = page["finding-grid"]["innerHTML"]
        self.assertEqual(chart.count('class="f-row"'), 4)
        for name, rate, n in [("Iran", "74.5%", "3,006"), ("India", "52.4%", "3,926"),
                              ("Brazil", "40.2%", "1,442"), ("Mainland China", "19.1%", "8,610")]:
            for text in (name, rate, n):
                self.assertIn(text, chart)
        for tick in ("0%", "25%", "50%", "75%", "100%"):
            self.assertIn(tick, chart)
        self.assertIn('data-stratum="long" aria-pressed="true">4+ years', (ROOT / 'index.html').read_text())
        self.assertIn("US", page["finding-h"]["textContent"])

    def test_four_outcomes_are_one_whole_with_plain_definitions(self):
        page = render()
        chart = page["finding-grid"]["innerHTML"]
        self.assertEqual(chart.count('class="bar"'), 4)
        self.assertEqual(chart.count('title="'), 16)
        widths = [float(w) for w in re.findall(r'width:([\d.]+)%', chart)]
        self.assertEqual(len(widths), 16)
        for row, cc in enumerate(("ir", "in", "br", "cn")):
            data = json.loads((ROOT / f"data/data-{cc}.json").read_text())
            s = next(c for c in data["countries"] if c["cc"] == "us")["strata"]["long"]
            for part, key in enumerate(("stay", "dual", "ret", "onward")):
                self.assertAlmostEqual(widths[row * 4 + part], s[key] * 100)
            self.assertAlmostEqual(sum(widths[row * 4:row * 4 + 4]), 100, delta=0.02)
        legend = page["finding-legend"]["innerHTML"]
        for definition in ("destination, no origin", "destination + origin", "origin, no destination", "third country"):
            self.assertIn(definition, legend)
        self.assertIn("100%", page["finding-whole"]["textContent"])

    def test_relative_comparison_warning_is_directly_under_chart_in_both_languages(self):
        html = (ROOT / "index.html").read_text()
        self.assertRegex(html[html.index('<section class="finding atlas"'):html.index('<!-- Path finder -->')],
                         r'id="finding-grid"[^>]*></div>\s*<p[^>]*id="finding-limit"')
        for lang, words in [("en", ("relative levels", "sample frames", "absolute percentages")),
                            ("zh", ("相对", "样本框", "绝对百分比"))]:
            with self.subTest(lang=lang):
                limit = render(lang)["finding-limit"]["textContent"]
                for word in words:
                    self.assertIn(word, limit)

    def test_chart_responds_to_data_including_sample_size_and_interval(self):
        chart = render(changed=True)["finding-grid"]["innerHTML"]
        for text in ("50.0%", "600", "46.0%", "54.0%", "width:50%"):
            self.assertIn(text, chart)
        self.assertNotIn("74.5%", chart)

    def test_opening_chart_reuses_percentage_axis_with_real_intervals_and_counts(self):
        chart = render(changed=True)["finding-chart"]["innerHTML"]
        self.assertEqual(chart.count('class="ci-row"'), 4)
        for text in ("Iran", "50.0%", "600", "46.0%", "54.0%", "0%", "100%"):
            self.assertIn(text, chart)
        self.assertNotIn("74.5%", chart)

    def test_opening_controls_explain_cohort_and_link_to_comparison(self):
        html = (ROOT / "index.html").read_text()
        comparison = html[html.index('<aside class="comparison">'):html.index('</aside>')]
        self.assertIn('id="finding-cta"', comparison)
        self.assertIn('id="cohort-more"', comparison)
        for lang, words in [("en", ("Published at home", "US affiliation")),
                            ("zh", ("来源国", "美国"))]:
            definition = render(lang)["cohort-definition"]["textContent"]
            for word in words:
                self.assertIn(word, definition)
        self.assertNotIn("one genuinely interesting thing this site has to show", html)

    def test_opening_actions_route_to_comparison_and_definitions(self):
        # Run the shipped handlers with a short-stay selection already in state.
        script = r'''
const fs = require('fs'), vm = require('vm');
const html = fs.readFileSync('index.html', 'utf8');
const start = html.indexOf("document.getElementById('cohort-more').onclick");
const end = html.indexOf("document.querySelector('.tabs').onclick", start);
const nodes = {};
const context = { S: {view:'match', stratum:'short'}, render() {}, syncHash() {},
  document: {getElementById(id) {return nodes[id] ||= {scrollIntoView() {}}},
             querySelector() {return {focus() {}}}} };
vm.runInNewContext(html.slice(start, end), context);
nodes['finding-cta'].onclick();
if (context.S.view !== 'compare' || context.S.stratum !== 'short') process.exit(1);
nodes['cohort-more'].onclick();
if (context.S.view !== 'doc' || context.S.stratum !== 'short') process.exit(2);
'''
        subprocess.run(['node', '-e', script], cwd=ROOT, check=True)


if __name__ == "__main__":
    unittest.main()
