// Runs the ORIGINAL dashboard data/scoring code under Node (DOM stubbed) and writes a reference fixture.
// Usage: node scripts/export_reference.js <path-to-original-script.js> <out.json>
const fs = require('fs');
const [src, out] = process.argv.slice(2);
let code = fs.readFileSync(src, 'utf8');
// Keep data + scoring + trust checks; drop the DOM wiring that follows the "ui helpers" marker.
code = code.split('// ---- ui helpers ----')[0];
code += `\nreturn {CO, CASES, TT, M, CFG, T, REV, checks: checks(), trust: trust(), agree: agree(), groups: groups()};`;
const res = new Function(code)();
fs.writeFileSync(out, JSON.stringify(res));
console.log('cases', res.CASES.length, 'gaps', res.CASES.filter(p => p.gap).length, 'trust', res.trust);
