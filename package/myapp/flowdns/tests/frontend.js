/* Exercise actual LuCI modules with DOM/RPC adapters; no router is modified. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
String.prototype.format = function(...args) { let i = 0; return this.replace(/%s/g, () => args[i++]); };
const resources = process.argv[2] || 'package/myapp/luci-app-flowdns/htdocs/luci-static/resources';
const source = fs.readFileSync(path.join(resources, 'flowdns/ui_v2.js'), 'utf8');
function E(tag, attrs = {}, content = []) {
	return { tag, attrs, content, style: { display: /display:none/.test(attrs.style || '') ? 'none' : '' },
		children: Array.isArray(content) ? content : [], addEventListener() {},
		set textContent(value) { this.content = value; this.children = []; },
		get firstElementChild() { return this.children[0]; } };
}
function fixture(statuses, submission = { ok: true, id: 'task-1' }, manual = false) {
	let polls = 0;
	const timers = [];
	const rpc = { declare(spec) { return () => {
		if (spec.method === 'action') return Promise.resolve(submission);
		polls++;
		const status = statuses.shift();
		if (status instanceof Error) return Promise.reject(status);
		assert.ok(status, 'unexpected extra poll');
		return Promise.resolve(status);
	}; } };
	const dom = { content(node, children) { node.children = Array.isArray(children) ? children : [children]; } };
	const api = new Function('rpc', 'dom', 'L', '_', 'E', 'window', source)(rpc, dom,
		{ Class: { extend: d => d }, url: (...parts) => parts.join('/') }, text => text, E,
		{ setTimeout: callback => manual ? timers.push(callback) : queueMicrotask(callback) });
	return { api, dom, timers, polls: () => polls, node: api.feedback() };
}
function text(f) { return f.node.children[0].content; }
function close(f) {
	const button = f.node.children[1];
	assert.equal(button.attrs.type, 'button');
	let prevented = false;
	button.attrs.click({ preventDefault() { prevented = true; } });
	assert.ok(prevented);
	assert.equal(f.node.style.display, 'none');
}
(async () => {
	let f = fixture([{ job: { id: 'task-1', state: 'error', result: { message: 'SSR Plus 仍在接管' } } }]);
	assert.equal((await f.api.action('apply')).ok, false);
	assert.equal(text(f), 'SSR Plus 仍在接管');
	assert.equal(f.node.style.display, 'flex');
	close(f);
	console.log('PASS: actual failure appears inline and its close button hides it without a modal');
	f = fixture([
		{ job: { id: 'task-1', state: 'running', message: '正在下载规则' } },
		{ job: { id: 'task-1', state: 'done', result: { ok: true, message: '接管已启动' } } }
	], undefined, true);
	const action = f.api.action('apply');
	await new Promise(setImmediate);
	assert.equal(text(f), '正在下载规则');
	close(f);
	assert.equal(f.polls(), 1);
	f.timers.shift()();
	assert.equal((await action).ok, true);
	assert.equal(f.polls(), 2);
	assert.equal(text(f), '接管已启动');
	assert.equal(f.node.style.display, 'flex');
	close(f);
	console.log('PASS: hiding progress keeps the worker poll active; actual completion reappears and can be closed');
	f = fixture([{ job: { id: 'task-2', state: 'done', result: { ok: true } } }]);
	assert.equal((await f.api.action('apply')).ok, false);
	f = fixture([], { ok: false, message: '正在执行其他任务' });
	assert.equal((await f.api.action('update')).ok, false);
	assert.equal(f.polls(), 0);
	assert.equal(text(f), '正在执行其他任务');
	f = fixture([], { ok: true, message: '任务已提交' });
	assert.equal((await f.api.action('apply')).ok, false);
	assert.equal(f.polls(), 0);
	console.log('PASS: wrong task IDs, rejected submissions and missing IDs never report successful apply');
	f = fixture([{ job: { id: 'task-1', state: 'error', result: { ok: false, message: '诊断发现问题' } } }]);
	assert.equal((await f.api.action('diagnose')).ok, false);
	assert.ok(JSON.stringify(f.api.setup({ setup: [{ ready: false, title: 'SSR', detail: '启用 SOCKS5', link: 'ssr_advanced' }] })).includes('admin/services/shadowsocksr/advanced'));

	const menuPath = 'package/myapp/luci-app-flowdns/root/usr/share/luci/menu.d/luci-app-flowdns.json';
	const menu = JSON.parse(fs.readFileSync(menuPath));
	const children = Object.entries(menu).filter(([key]) => key.startsWith('admin/services/flowdns/')).sort((a, b) => a[1].order - b[1].order);
	assert.equal(children[0][0], 'admin/services/flowdns/diagnostics');
	for (const [, item] of children) {
		const view = fs.readFileSync(path.join(resources, 'view', item.action.path + '.js'), 'utf8');
		assert.ok(view.includes("'require flowdns.ui_v2 as api'"));
		assert.ok(!view.includes("'require flowdns as api'"));
		assert.ok(view.includes('api.feedback()'));
	}
	const diagnostic = fs.readFileSync(path.join(resources, 'view/flowdns/v2/diagnostics.js'), 'utf8');
	const page = new Function('view', 'poll', 'dom', 'api', '_', 'E', diagnostic)(
		{ extend: d => d }, { add() {} }, f.dom, f.api, t => t, E);
	assert.doesNotThrow(() => page.render({ running: true, dns_ready: true, attached: true }));
	assert.ok(JSON.stringify(page.render({ running: true, state: 'recovering', egress_ready: false })).includes('恢复中，后台快速检查'));
	assert.ok(JSON.stringify(page.render({ running: true, state: 'ready', egress_ready: true })).includes('加密 DNS 及代理出口已验证'));
	assert.ok(JSON.stringify(page.render({ running: true, active: { mode: 'transparent', provider: 'ssrplus', ssr_node: 'fixture-node', proxy_port: 1080 } })).includes('Xray · fixture-node'));
	assert.ok(!source.includes('showModal') && !source.includes('addNotification') && !diagnostic.includes('showModal'));
	console.log('PASS: default tab is diagnostics; both views use fresh module paths and status renders without the cached old API');
})().catch(error => { console.error(error); process.exit(1); });
