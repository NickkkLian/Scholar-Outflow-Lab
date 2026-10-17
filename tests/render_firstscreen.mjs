// Exercise the page's real headline renderer with published data, without a browser or packages.
import fs from 'node:fs';
import vm from 'node:vm';
const page = fs.readFileSync(new URL('../index.html', import.meta.url), 'utf8');
const elements = Object.fromEntries([...page.matchAll(/id="([^"]+)"/g)].map(([, id]) => [id, {innerHTML:'', textContent:'', hidden:false}]));
const context = vm.createContext({
  LANG: process.argv[2] || 'en', location:{hash:''}, URLSearchParams, Intl,
  document:{getElementById:id => {
    if(!elements[id]) throw new Error(`Missing page element: ${id}`);
    return elements[id];
  }},
  country:(cc, name) => name,
});
vm.runInContext(page.slice(page.indexOf('const T = {'), page.indexOf('function renderCountries()')), context);
vm.runInContext(page.slice(page.indexOf('const FINDING_ORIGINS ='), page.indexOf('/* ── compare chart:')), context);
const data = Object.fromEntries(['ir','in','br','cn'].map(cc => [cc, JSON.parse(fs.readFileSync(new URL(`../data/data-${cc}.json`, import.meta.url)))]));
if(process.argv[3] === 'changed') {
  const s = data.ir.countries.find(c => c.cc === 'us').strata.long;
  Object.assign(s, {stay:0.5, dual:0.2, ret:0.2, onward:0.1, n:600, stay_ci:[0.46,0.54]});
}
context.data = data;
vm.runInContext('S.allData = data; renderFinding();', context);
console.log(JSON.stringify(elements));
