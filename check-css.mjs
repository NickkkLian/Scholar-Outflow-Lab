/* check-css.mjs — every class the app puts on an element has a rule, and every rule is for a class it puts there.

     node check-css.mjs           reports classes with no rule, and rules for classes nothing renders
     node check-css.mjs --break   deletes one rule at a time in a copy and requires the report to name that class

   This exists because of a real regression in this repository. Restyling the app onto the design tokens rewrote
   styles.css, the markup kept every class name it had, and twenty-one rules were quietly not carried over: error
   messages rendered in the neutral info style, the image gallery lost its grid and stacked full-width, the sync pill
   lost its three states. Nothing threw and nothing looked obviously broken in the states a screenshot happened to
   catch — which is exactly the shape of defect a person does not find by looking.

   How the classes are found, since there is no build step to ask:
     · anything inside a class="…" / class='…' — HTML attributes, and the ones assembled inside JS string literals
       (the capture stops at the first quote of either kind, so `'<b class="chip' + (on ? ' chip--on' : '')` yields
       `chip` here and `chip--on` from the rule below);
     · any string literal that is nothing but class-shaped tokens, one of which carries a `--`, a `__` or an `is-`
       prefix — the modifiers the render functions concatenate.
     · a literal assigned to .className, or passed to classList.add / remove / toggle / contains;
     · a `class:` property in an object literal, for pages that build their DOM in code rather than in markup.
   A class named by none of those routes is invisible to this check, and so is the difference between a class that has
   one declaration somewhere and a class that is fully styled: this catches a rule that went missing, not a rule that
   says too little. */
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const IGNORE = new Set(['node_modules', '.git', 'vendor', '__pycache__', 'dist', 'build']);

/* The files are found rather than listed, so this file is the same in every repository that uses it: some keep their
   CSS in .css files beside the page, some keep it in a <style> block inside the page, and both count as rules. */
function walk(dir, out = []) {
  for (const e of fs.readdirSync(path.join(HERE, dir || '.'), { withFileTypes: true })) {
    const rel = dir ? dir + '/' + e.name : e.name;
    if (e.isDirectory()) { if (!IGNORE.has(e.name) && !e.name.startsWith('.')) walk(rel, out); }
    else out.push(rel);
  }
  return out;
}
const ALL = walk('');
const SOURCES = ALL.filter((f) => (f.endsWith('.html') || f.endsWith('.js')) && !/\.min\.js$/.test(f) && !f.endsWith('.mjs'));
const CSS_FILES = ALL.filter((f) => f.endsWith('.css') && !/\.min\.css$/.test(f));
const STYLE_BLOCK = /<style[^>]*>([\s\S]*?)<\/style>/g;

/* check-css-known.json, when it exists beside this file, is the list of reports that have been looked at and ruled
   on: { "dead": {"<class>": "why"}, "built": {"<fragment>": "why"}, "unstyled": {"<class>": "why"} }. A listed item
   is printed with its reason and does not fail the run; an item in the file that is no longer reported fails, so a
   list cannot quietly outlive what it excused. Every entry needs a reason a reader can check — "known" is not one. */
function known() {
  try { return JSON.parse(fs.readFileSync(path.join(HERE, 'check-css-known.json'), 'utf8')); }
  catch { return {}; }
}

/* In a place that can only be a class — a class attribute, a class: property, classList, .className — anything
   CSS accepts is a class: one letter (.n, .m, .x are all real here), a capital (.R1), an underscore. The stricter
   shape below is for the guess: a string literal that merely looks like a class list. */
const IN_CLASS_POSITION = /^[A-Za-z_][\w-]*$/;
const WHOLE = /^[a-z][a-z0-9_-]*[a-z0-9]$/;      // a class name, ending in a character and not a separator
const PREFIX = /^[a-z][a-z0-9_-]*[-_]$/;         // what is left of one when a variable was going to finish it
const MODIFIER = /(--|__)|^is-/;

function classesInSources() {
  const found = new Map();      // class -> the files that name it
  const partial = new Map();    // prefix -> the files that build a class name out of it
  for (const rel of SOURCES) {
    /* Comments are not markup: this file's own prose about class names must not be read as class names. */
    const text = fs.readFileSync(path.join(HERE, rel), 'utf8')
      .replace(/\/\*[\s\S]*?\*\//g, ' ').replace(/<!--[\s\S]*?-->/g, ' ');
    const into = (map, token) => {
      if (!map.has(token)) map.set(token, new Set());
      map.get(token).add(rel);
    };
    for (const m of text.matchAll(/class=["']([^"'\n]*)/g)) {
      m[1].trim().split(/\s+/).forEach((p) => {
        if (IN_CLASS_POSITION.test(p)) into(found, p);
        else if (p.includes('${')) into(partial, p);          // class="tag ${kind}" — the name is decided at run time
      });
    }
    /* Pages that build their DOM in code pass the class as a property rather than writing an attribute:
       h('div', { class: 'tablewrap' }, …). Without this the checker sees almost none of such a page's classes and
       reports nearly every rule as dead — which is how it read the first time it was pointed at Query Mirror. */
    for (const m of text.matchAll(/\bclass\s*:\s*(['"])([^'"\n]*)\1/g)) {
      m[2].trim().split(/\s+/).forEach((p) => { if (IN_CLASS_POSITION.test(p)) into(found, p); });
    }
    /* Set on an element directly rather than rendered into markup. */
    for (const m of text.matchAll(/\.className\s*=\s*(['"])([^'"\n]*)\1/g)) {
      m[2].trim().split(/\s+/).forEach((p) => { if (IN_CLASS_POSITION.test(p)) into(found, p); });
    }
    for (const m of text.matchAll(/classList\.(?:add|remove|toggle|contains)\(([^)]*)\)/g)) {
      for (const lit of m[1].matchAll(/(['"])([^'"\n]*)\1/g)) {
        lit[2].trim().split(/\s+/).forEach((p) => { if (IN_CLASS_POSITION.test(p)) into(found, p); });
      }
    }
    /* A string literal that is nothing but class-shaped words, one of them a modifier: the pieces the render
       functions concatenate. A piece left hanging on a separator was going to be completed by a variable. */
    for (const m of text.matchAll(/(['"])([^'"\n]*)\1/g)) {
      const parts = m[2].trim().split(/\s+/).filter(Boolean);
      if (!parts.length || !parts.every((p) => WHOLE.test(p) || PREFIX.test(p))) continue;
      if (!parts.some((p) => MODIFIER.test(p))) continue;
      parts.forEach((p) => into(WHOLE.test(p) ? found : partial, p));
    }
  }
  return { found, partial };
}

/* Selectors only: a rule's declarations can hold a data: URI with dots in it, and did. */
function classesInSheets(sheets) {
  const found = new Map();
  for (const [rel, raw] of sheets) {
    const text = raw.replace(/\/\*[\s\S]*?\*\//g, '');
    for (const rule of text.matchAll(/([^{}]*)\{[^{}]*\}/g)) {
      for (const m of rule[1].matchAll(/\.(-?[A-Za-z_][\w-]*)/g)) {
        if (!found.has(m[1])) found.set(m[1], new Set());
        found.get(m[1]).add(rel);
      }
    }
  }
  return found;
}

function report(sheets) {
  const { found: inSource, partial } = classesInSources();
  const inSheet = classesInSheets(sheets);
  const unstyled = [...inSource.keys()].filter((c) => !inSheet.has(c)).sort();
  const dead = [...inSheet.keys()].filter((c) => !inSource.has(c)).sort();
  return { unstyled, dead, inSource, partial };
}

/* Every stylesheet in the repository: the .css files, and each <style> block of each page, named so a report can
   point at it. `swap` replaces one file's text, for the --break run. */
function readSheets(swap) {
  const text = (rel) => (swap && swap[rel] !== undefined) ? swap[rel] : fs.readFileSync(path.join(HERE, rel), 'utf8');
  const out = CSS_FILES.map((rel) => [rel, text(rel)]);
  for (const page of SOURCES.filter((f) => f.endsWith('.html'))) {
    const src = text(page);
    let m, i = 0;
    STYLE_BLOCK.lastIndex = 0;
    while ((m = STYLE_BLOCK.exec(src))) out.push([`${page} <style> #${++i}`, m[1]]);
  }
  /* A script can carry its own stylesheet as strings and put it into the page at run time — the shared appearance
     kit does, which is why its .nl-* classes read as unstyled until this looked inside the script too. Any string
     literal that is a rule (a selector, a brace, a declaration with a colon) counts as a sheet. */
  for (const js of SOURCES.filter((f) => f.endsWith('.js'))) {
    const rules = [];
    for (const lit of text(js).matchAll(/(['"`])((?:[^\\\n]|\\.)*?)\1/g)) {
      const v = lit[2];
      if (v.includes('{') || v.includes('}')) rules.push(v);   // one rule is often split across several literals
    }
    if (rules.length) out.push([`${js} (css in strings)`, rules.join('')]);
  }
  return out;
}

/* The file whose rules this repository mostly lives in — where --break deletes from. */
function primarySheet() {
  let best = null, most = -1;
  for (const rel of [...CSS_FILES, ...SOURCES.filter((f) => f.endsWith('.html'))]) {
    const text = fs.readFileSync(path.join(HERE, rel), 'utf8');
    const n = (text.match(/\{[^{}]*\}/g) || []).length;
    if (n > most) { most = n; best = rel; }
  }
  return best;
}

/* Delete every rule whose selector list mentions .name — the whole declaration block with it. */
function deleteRulesFor(css, name) {
  let out = '', i = 0, removed = 0;
  const re = /([^{}]+)\{([^{}]*)\}/g;   // one flat rule; nested at-rules keep their own braces around these
  let m;
  while ((m = re.exec(css))) {
    const selector = m[1];
    if (new RegExp('\\.' + name + '(?![\\w-])').test(selector)) {
      out += css.slice(i, m.index);
      i = m.index + m[0].length;
      removed++;
    }
  }
  out += css.slice(i);
  return { css: out, removed };
}

function main() {
  if (!process.argv.includes('--break')) {
    const { unstyled, dead, inSource, partial } = report(readSheets());
    const sheetNames = readSheets().map(([rel]) => rel).join(', ');
    const ruled = known();
    const seen = { unstyled: new Set(), dead: new Set(), built: new Set() };
    let open = 0;
    const say = (kind, key, line) => {
      const why = (ruled[kind] || {})[key];
      if (why) { seen[kind].add(key); console.log(`KNOWN     ${line}\n          ↳ ${why}`); }
      else { open++; console.log(line); }
    };
    for (const c of unstyled) say('unstyled', c, `UNSTYLED  .${c} — rendered by ${[...inSource.get(c)].join(', ')}, no rule in ${sheetNames}`);
    for (const c of dead) say('dead', c, `DEAD      .${c} — a rule exists, nothing renders it`);
    for (const [c, where] of partial) say('built', c, `BUILT     .${c}… — ${[...where].join(', ')} completes this name with a variable, so no check can see it; put the whole names in a table`);
    let stale = 0;
    for (const kind of ['unstyled', 'dead', 'built']) {
      for (const key of Object.keys(ruled[kind] || {})) {
        if (!seen[kind].has(key)) { stale++; console.log(`STALE     ${kind} "${key}" is in check-css-known.json and is no longer reported — delete the entry`); }
      }
    }
    console.log(`RESULT: ${inSource.size} classes rendered, ${unstyled.length} with no rule, ${dead.length} rules nothing renders, ` +
      `${partial.size} names built at runtime · ${open} open, ${stale} stale entries`);
    return open || stale ? 1 : 0;
  }

  /* The check can only be trusted if removing a rule turns it red, and reddens it for that class. The classes to
     try are taken from the stylesheet rather than listed here — a list would be one more thing to keep in step with
     the sheet, and the point is only that deleting a rule is noticed, whichever rule it is. */
  const sheetFile = primarySheet();
  const styles = fs.readFileSync(path.join(HERE, sheetFile), 'utf8');
  const candidates = [...report(readSheets()).inSource.keys()]
    .filter((c) => deleteRulesFor(styles, c).removed === 1).sort();
  const WANT = 8;
  if (candidates.length < WANT) {
    console.log(`NOT APPLIED  only ${candidates.length} classes in ${sheetFile} have exactly one rule to delete`);
    return 1;
  }
  // spread across the sheet rather than the first eight, which would all come from one corner of the alphabet
  const probes = Array.from({ length: WANT }, (_, i) => candidates[Math.floor((i * candidates.length) / WANT)]);
  const caught = [];
  for (const name of probes) {
    const { css, removed } = deleteRulesFor(styles, name);
    if (!removed) {
      console.log(`NOT APPLIED  .${name} — no rule to delete in ${sheetFile}`);
      caught.push(false);
      continue;
    }
    const { unstyled } = report(readSheets({ [sheetFile]: css }));
    const ok = unstyled.includes(name);
    console.log(`${ok ? 'CAUGHT     ' : 'NOT CAUGHT '} .${name} (${removed} rule${removed === 1 ? '' : 's'} deleted from ${sheetFile})` +
      (ok ? '' : `\n             reported instead: ${unstyled.join(', ') || 'nothing'}`));
    caught.push(ok);
  }
  const n = caught.filter(Boolean).length;
  console.log(`RESULT: ${n}/${probes.length} deleted rules reported as unstyled`);
  return n === probes.length ? 0 : 1;
}

process.exit(main());
