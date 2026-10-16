// Headless front-end check: loads the real dashboard + patients page (jsdom) against a RUNNING server.
// Usage: BASE_URL=http://127.0.0.1:8000 node dashboard.e2e.js
const { JSDOM, VirtualConsole } = require('jsdom');
const BASE = process.env.BASE_URL || 'http://127.0.0.1:8000';
const sleep = ms => new Promise(r => setTimeout(r, ms));
let fails = 0; const errors = [];
const ok = (c, m) => { console.log((c ? 'PASS ' : 'FAIL ') + m); if (!c) fails++; };

async function open(path) {
  const vc = new VirtualConsole();
  vc.on('jsdomError', e => errors.push(String(e.message || e)));
  vc.on('error', e => errors.push(String(e)));
  const dom = await JSDOM.fromURL(BASE + path, { runScripts: 'dangerously', resources: 'usable', pretendToBeVisual: true, virtualConsole: vc,
    beforeParse(w) { w.fetch = (u, o) => fetch(new URL(u, BASE), o); w.matchMedia = w.matchMedia || (() => ({ matches: false, addListener() {}, addEventListener() {} }));
      w.HTMLDialogElement.prototype.showModal = function () { this.open = true; }; w.HTMLDialogElement.prototype.close = function () { this.open = false; }; } });
  if (path === '/' && !(await until(() => !!dom.window.document.querySelector('#lf')?.onsubmit))) {
    throw new Error('Dashboard login handler did not initialize');
  }
  return dom;
}
async function until(fn, ms = 4000) { const t = Date.now(); while (Date.now() - t < ms) { if (fn()) return true; await sleep(50); } return false; }
async function apiToken(role, email, password) {
  const response = await fetch(BASE + '/api/auth/login', { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ role, email, password }) });
  if (!response.ok) throw new Error('Could not sign in as ' + role + ': ' + await response.text());
  return (await response.json()).access_token;
}
async function signInPage(w, role, email, password) {
  const d = w.document;
  d.querySelector('#out').click();
  if (!(await until(() => d.querySelector('#login').style.display !== 'none'))) throw new Error('Sign-out did not return to login');
  d.querySelector('#lr').value = role;
  d.querySelector('#em').value = email;
  d.querySelector('#pw').value = password;
  d.querySelector('#lf').dispatchEvent(new w.Event('submit', { cancelable: true }));
  if (!(await until(() => !d.querySelector('#app').hidden))) throw new Error('Could not load ' + role + ': ' + d.querySelector('#e3').textContent);
}

(async () => {
  // ---------- dashboard as Doctor ----------
  let dom = await open('/'); let w = dom.window, d = w.document;
  ok(d.querySelector('#login').style.display !== 'none', 'login screen shown first');
  d.querySelector('#em').value = 'bad'; d.querySelector('#pw').value = 'x';
  d.querySelector('#lf').dispatchEvent(new w.Event('submit', { cancelable: true }));
  ok(/valid email/.test(d.querySelector('#e1').textContent), 'client-side email validation: ' + d.querySelector('#e1').textContent);
  d.querySelector('#em').value = 'doctor@demo.org'; d.querySelector('#pw').value = 'wrongpass';
  d.querySelector('#lf').dispatchEvent(new w.Event('submit', { cancelable: true }));
  ok(await until(() => /Sign-in failed/.test(d.querySelector('#e3').textContent)), 'wrong password rejected by API with helpful feedback: ' + d.querySelector('#e3').textContent);
  d.querySelector('#pw').value = 'DoctorDemo2026!';
  d.querySelector('#lf').dispatchEvent(new w.Event('submit', { cancelable: true }));
  ok(await until(() => !d.querySelector('#app').hidden && /Welcome, Dr\. Demo/.test(d.querySelector('#mn').textContent)), 'email sign-in loads dashboard from API');
  ok(/Patient Care Records/.test(d.querySelector('#mn').textContent) && /demo patients/.test(d.querySelector('#mn').textContent), 'overview shows live patient-record counts');
  ok(!d.querySelector('#mn').classList.contains('page-secondary'), 'Overview keeps its existing page styling');
  d.querySelector('#th').click();
  ok(w.document.documentElement.dataset.theme === 'dark' && w.sessionStorage.getItem('mb_theme') === 'dark', 'dashboard dark mode is saved for the shared workspace');
  const REF = require('../fixtures/reference.json');
  ok(JSON.stringify(w.eval('trust()')) === JSON.stringify(REF.trust) && JSON.stringify(w.eval('agree()')) === JSON.stringify(REF.agree), 'trust score + reviewer agreement computed from API data equal the original dashboard (' + JSON.stringify(REF.trust).slice(0,40) + ')');
  const nav = [...d.querySelectorAll('#nv button')].map(b => b.textContent.trim());
  ok(nav.includes('Patient Records') && !nav.includes('Audit Log') && !nav.includes('Reports'), 'doctor nav limits access to patient workflows: ' + nav.join(' | '));
  for (const p of ['gaps', 'cohorts', 'trust']) { w.eval(`go('${p}')`); await sleep(150); ok(d.querySelector('#mn').textContent.length > 200 && d.querySelector('#mn').classList.contains('page-secondary'), 'page renders with shared secondary styling: ' + p); }
  w.eval("go('overview')");
  ok(!d.querySelector('#mn').classList.contains('page-secondary'), 'returning to Overview removes secondary-page styling');
  w.eval("go('gaps')"); await sleep(150);
  const row = d.querySelector('#mn [onclick^="openCase"], #mn tr[onclick], #mn [data-id]');
  const idMatch = /SYN-\d{4}/.exec(d.querySelector('#mn').innerHTML);
  ok(!!idMatch, 'case IDs visible to doctor');
  const pending = w.eval("CASES.find(p=>p.gap&&p.rv.st=='Pending').id");
  w.openCase(pending); await sleep(150);
  ok(!d.querySelector('#rs'), 'doctor can inspect case summary but cannot perform reviewer actions');
  await signInPage(w, 'reviewer', 'reviewer@demo.org', 'ReviewerDemo2026!');
  ok(await until(() => w.eval('ROLE') === 'reviewer'), 'reviewer signs in with a separate account');
  w.eval("go('reports')"); await sleep(150);
  ok(d.querySelector('#mn').textContent.includes('Export CSV') && d.querySelector('#mn').classList.contains('page-secondary'), 'reviewer retains reports access');
  w.eval("go('gaps')");
  w.openCase(pending); await sleep(150);
  ok(!!d.querySelector('#rs'), 'reviewer evidence panel includes review controls');
  d.querySelector('#rs').value = 'Under Review'; d.querySelector('#rn').value = 'e2e check';
  w.applySt(pending);
  ok(await until(() => w.eval(`CASES.find(p=>p.id=='${pending}').rv.st`) === 'Under Review'), 'status change saved through API');
  ok(w.eval(`CASES.find(p=>p.id=='${pending}').rv.log[0]`).includes('e2e check'), 'log entry returned from API');
  w.openCase(pending); await sleep(100); d.querySelector('#rn').value = '';
  w.fbk(pending, 'Wrong flag'); await sleep(200);
  ok(/note is required/i.test(d.querySelector('#rm') ? d.querySelector('#rm').textContent : ''), 'feedback without note is blocked client-side');
  d.querySelector('#rn').value = 'evidence existed'; w.fbk(pending, 'Wrong flag');
  ok(await until(() => w.eval(`CASES.find(p=>p.id=='${pending}').rv.fb`) === 'Wrong flag'), 'feedback saved through API');
  // Manager uses a separate authenticated account rather than a client-side role switch.
  await signInPage(w, 'manager', 'manager@demo.org', 'ManagerDemo2026!');
  ok(await until(() => w.eval('ROLE') === 'manager' && w.eval('CASES.every(p=>p.id===null)')), 'manager role: API withholds case IDs');
  ok(await until(() => [...d.querySelectorAll('#nv button')].some(b => /Audit Log/.test(b.textContent))), 'manager sees Audit Log nav');
  w.eval("go('audit')"); ok(await until(() => /case_status_changed/.test(d.querySelector('#mn').textContent) && d.querySelector('#mn').classList.contains('page-secondary')), 'audit page lists review activity with shared secondary styling');
  w.eval("go('gaps')"); await sleep(200); ok(!/SYN-\d{4}/.test(d.querySelector('#mn').innerHTML), 'manager gaps page shows no case IDs');
  await signInPage(w, 'administrator', 'admin@demo.org', 'AdminDemo2026!');
  ok(await until(() => w.eval('ROLE') === 'administrator'), 'administrator signs in with a separate account');
  ok([...d.querySelectorAll('#nv button')].some(b => /User & Access/.test(b.textContent)) &&
    [...d.querySelectorAll('#nv button')].some(b => /Settings/.test(b.textContent)), 'administrator navigation exposes account and settings tools');
  w.eval("go('users')");
  ok(await until(() => !!d.querySelector('#userForm') && d.querySelectorAll('[data-save-user]').length >= 4), 'admin user-management page loads database accounts');
  d.querySelector('#userForm [name=email]').value = 'e2e.user@demo.org';
  d.querySelector('#userForm [name=display_name]').value = 'E2E User';
  d.querySelector('#userForm [name=password]').value = 'E2EUserPassword2026!';
  d.querySelector('#userForm').dispatchEvent(new w.Event('submit', { cancelable: true }));
  ok(await until(() => [...d.querySelectorAll('#mn tbody tr')].some(r => r.textContent.includes('e2e.user@demo.org'))), 'administrator creates an account through the API');
  w.eval("go('settings')");
  ok(await until(() => !!d.querySelector('#settingsForm')), 'admin settings form loads');
  d.querySelector('#settingsForm [name=min_cohort_size]').value = '11';
  d.querySelector('#settingsForm').dispatchEvent(new w.Event('submit', { cancelable: true }));
  ok(await until(() => w.eval('CFG.minN') === 11), 'administrator saves allowed trust settings through the API');
  ok(![...d.querySelectorAll('#nv button')].some(b => /Patient Records/.test(b.textContent)), 'administrator does not receive patient-record navigation');
  // reload keeps session
  const tok = w.sessionStorage.getItem('mb_token'), savedTheme = w.sessionStorage.getItem('mb_theme'); ok(!!tok, 'token stored in sessionStorage');
  dom.window.close();

  // ---------- fresh Patient Records page, shared login ----------
  const t2 = await apiToken('doctor', 'doctor@demo.org', 'DoctorDemo2026!');
  const vc = new VirtualConsole(); vc.on('jsdomError', e => errors.push(String(e.message)));
  const pdom = await JSDOM.fromURL(BASE + '/patients.html', { runScripts: 'dangerously', resources: 'usable', pretendToBeVisual: true, virtualConsole: vc,
    beforeParse(win) { win.fetch = (u, o) => fetch(new URL(u, BASE), o); win.sessionStorage.setItem('mb_token', t2); win.sessionStorage.setItem('mb_role', 'doctor'); if (savedTheme) win.sessionStorage.setItem('mb_theme', savedTheme);
      win.HTMLDialogElement.prototype.showModal = function () { this.open = true; }; win.HTMLDialogElement.prototype.close = function () { this.open = false; }; } });
  const pd = pdom.window.document; await sleep(1200);
  ok(pdom.window.document.documentElement.dataset.theme === 'dark', 'Patient Records inherits dashboard dark mode');
  pd.querySelector('#themeToggle').click();
  ok(pdom.window.document.documentElement.dataset.theme === 'light', 'Patient Records theme toggle updates the shared mode');
  ok(!pd.querySelector('#workspace').classList.contains('hidden'), 'patients page reuses the dashboard session (no second login)');
  ok(pd.querySelectorAll('#patientList button').length >= 4, 'patient directory loaded from API');
  pd.querySelector('#patientList button').click(); await sleep(600);
  ok(pd.querySelector('#treatmentTable').textContent.includes('Consultation'), 'patient detail + treatments from API');
  pd.querySelector('[data-tab="followups"]').click();
  ok(pd.querySelector('#followupTable').textContent.includes('Follow-up date listed'), 'follow-up tracker tab loads scheduled records from the API');
  pd.querySelector('[data-tab="quality"]').click();
  ok(pd.querySelectorAll('[data-review]').length === 0, 'doctor cannot access missing-data review controls');
  pdom.window.close();
  const reviewerToken = await apiToken('reviewer', 'reviewer@demo.org', 'ReviewerDemo2026!');
  const reviewerDom = await JSDOM.fromURL(BASE + '/patients.html', { runScripts: 'dangerously', resources: 'usable', pretendToBeVisual: true,
    beforeParse(win) { win.fetch = (u, o) => fetch(new URL(u, BASE), o); win.sessionStorage.setItem('mb_token', reviewerToken); win.sessionStorage.setItem('mb_role', 'reviewer');
      win.HTMLDialogElement.prototype.showModal = function () { this.open = true; }; win.HTMLDialogElement.prototype.close = function () { this.open = false; }; } });
  const rd = reviewerDom.window.document; await sleep(900);
  rd.querySelector('#patientList button').click(); await sleep(300);
  rd.querySelector('[data-tab="quality"]').click(); rd.querySelector('[data-review]').click(); await sleep(100);
  ok(rd.querySelector('#reviewDlg').open === true, 'review dialog opens (replaces prompt())');
  rd.querySelector('#reviewNote').value = 'checked source'; rd.querySelector('#reviewForm').dispatchEvent(new reviewerDom.window.Event('submit', { cancelable: true }));
  ok(await until(() => /Review saved/.test(rd.querySelector('#workspaceStatus').textContent)), 'quality review saved through API');
  await until(() => rd.querySelector('#qualityTable').textContent.includes('Verified'));
  await sleep(150);
  reviewerDom.window.close();

  const managerToken = await apiToken('manager', 'manager@demo.org', 'ManagerDemo2026!');
  const managerDom = await JSDOM.fromURL(BASE + '/patients.html', { runScripts: 'dangerously', resources: 'usable', pretendToBeVisual: true,
    beforeParse(win) { win.fetch = (u, o) => fetch(new URL(u, BASE), o); win.sessionStorage.setItem('mb_token', managerToken); win.sessionStorage.setItem('mb_role', 'manager'); } });
  const md = managerDom.window.document; await sleep(1000);
  ok(!md.querySelector('#workspace').classList.contains('hidden') && md.querySelectorAll('#patientList button').length >= 4, 'manager can view Patient Records');
  md.querySelector('#patientList button').click(); await sleep(500);
  ok(md.querySelector('#treatmentTable').textContent.includes('Consultation'), 'manager can view read-only patient detail');
  ok(md.querySelector('#newPatientBtn').style.display === 'none' && md.querySelector('#newTreatmentBtn').style.display === 'none' &&
    md.querySelector('#newFollowupBtn').style.display === 'none', 'manager cannot see patient or record creation actions');
  md.querySelector('[data-tab="quality"]').click();
  ok(md.querySelectorAll('[data-review]').length === 0 && /Read only/.test(md.querySelector('#qualityTable').textContent), 'manager cannot review patient quality issues');

  managerDom.window.close();
  const real = errors.filter(e => !/Could not load (link|script|img)/.test(e)); // offline CDN/fonts are not app bugs
  ok(real.length === 0, 'no uncaught JS errors in either page' + (real.length ? ': ' + real.slice(0, 3).join(' || ') : ''));
  console.log(fails ? `\n${fails} FAILED` : '\nALL E2E CHECKS PASSED'); process.exit(fails ? 1 : 0);
})().catch(e => { console.error('E2E crashed', e); process.exit(2); });
