# Scholar Outflow Lab: method notes

How the numbers were corrected along the way, what the tests check, and what the scheduled job learned. Moved here from the README so the README can lead with the findings.

## Three corrections that rescued the result

These are the reason the numbers are trustworthy, so they are documented rather than hidden.

1. **Dual affiliation had to become its own category.** The first version reported "stayed" and
   "did not return" as independent rates and produced *stayed 38% > did-not-return 25%* — a
   logical impossibility. The cause: a large share of Chinese researchers hold a foreign post
   *and* a home co-appointment at the same time. With four exclusive classes the totals are
   100% by construction and the numbers became self-consistent.
2. **Stratifying by length of stay is not optional.** The 2–3-year band is dominated by visiting
   scholars and joint-training students, who were always going home; pooled, they dilute every
   institution toward the same low rate. National University of Singapore, Chinese origin:
   **2.1%** stayed after 2–3 years (n=144), **10.7%** after ≥4 (n=289), **13.0%** after ≥6
   (n=185). The default stratum is ≥4 years for that reason.
3. **People already affiliated with the destination in their first year are not movers.**
   Without that filter, researchers who had always been in Taiwan or Hong Kong counted as
   "moved there and stayed" — 15.2% of ≥4-year arrivals — and a few Taiwanese universities
   topped the board. After the fix the top of the ranking returned to places that match
   intuition.

### And one hypothesis that did not survive

Early data suggested that much of computer science was being filed under "Engineering" because
the field label came from an author's *first* OpenAlex topic. The proposed fix — vote across all
topics — was implemented, and the entire Chinese sample was re-harvested under it
(235,059 authors, 31% larger than v1). Result: the share of CS relative to Engineering went from
15.6% to 14.5% — no improvement once sample growth is accounted for. The root cause is OpenAlex's
own topic→field taxonomy, which places applied CS under Engineering. The finding is recorded in
the pipeline comments so nobody re-runs the experiment, and the limitation is stated on the site.

## Pipeline guard

`compute.py` never publishes a half-finished re-harvest (it keeps using the previous file until the new
one has more rows), and `scripts/daily.sh` runs the rounds on a schedule within the free quota.

## Tests

```bash
python3 -m unittest discover -s tests -v
```

Python standard library, plus Node.js 22 for the first-screen renderer tests (built-in `vm`, no packages to install).
Three layers:

- **The first screen against the published data.** The page's real JavaScript renderer must show four origins on
  one percentage axis, with stay rates and sample sizes read from the JSON, four outcomes making a whole, plain
  definitions, and the relative-comparison warning immediately under the chart in English and Chinese. A changed
  input checks that the headline, sample size and interval respond to the data.

- **The pipeline against a plan it did not write.** `tests/make_fixture.py` generates 200 synthetic careers
  (origin `xa`, a private-use code; `Synthetic University …` institutions) and decides every person's
  destination, length of stay and final affiliation itself, writing the counts it intended to
  `tests/fixtures/expected.json`. The real `scripts/compute.py` then runs on those careers and every published
  count and fraction has to match. Ten further records each hit one exclusion rule (single-year visit,
  arrival inside the follow-up window, already there in the first year, started abroad, …) and must count
  nowhere. Separate cases pin dual affiliation as its own outcome, the stratum boundaries, one count per person
  per country, ranking by the Wilson lower bound rather than the raw rate, the no-timestamp-only-rewrite guard
  and the partial-re-harvest guard.
- **Invariants on the data the site serves.** For all thirteen `data-<cc>.json` files: the four outcomes sum to
  100% (within rounding) for every country, institution and field block; each stay rate sits inside its
  interval; ranks follow the lower bound and tiers are the quartiles; strata nest; nothing below the
  publication floor is published; `origins.json` matches the files; country and field names are English (no CJK
  characters; the page maps them to Chinese for its 中文 mode); and the headline table in the README is what the data says.

```bash
SOL_BREAK=1 python3 -m unittest discover -s tests
python3 tests/mutations.py
```

The first corrupts one fixture record and must fail. The second breaks one rule in `compute.py` or one number
in the published data at a time — 13 mutations — and requires the test guarding it to go red, so a
test that has stopped guarding anything is noticed.

## Automation, and what it learned the hard way

`scripts/daily.sh` runs once a week (launchd, Mondays 18:00 local — after the 00:00 UTC quota reset
in both daylight-saving regimes); until early September it ran every day. Tasks are ordered "cheapest
and most unlocking first", every step is resumable, and a run that runs out of quota simply continues
at the next one.

Three guards exist because each corresponding failure actually happened:

- **Never publish partial data.** During a multi-day re-harvest, `compute.py` uses whichever of
  the new file and its backup has more rows. The rule is dumb on purpose. It went in the same
  evening that a harvest hit the quota at 19k of 180k authors and the recompute ran anyway: on
  the live site, mainland China, the largest origin, shrank from 175 institutions to 3.
- **Only commit when the substance changed.** The generated timestamp is excluded from the
  comparison. The daily job's first trial run committed and pushed a data file whose only change
  was that timestamp; left alone, every scheduled run would have done the same. The job also
  stages data files only — never source: an early version staged the page as well, and a
  hand-made front-end change went out under a "data update" message.
- **Derive the country list from the files on disk.** Two origins were once harvested in full and
  then never computed or published, because a hard-coded list in the recompute loop wasn't
  updated. The loop now scans for `careers_*.jsonl`.

The job is now in maintenance mode: all queued work is complete, so a weekly run does exactly two
things — snapshot traffic and run an idempotent recompute — with zero OpenAlex quota and zero
attention required.
