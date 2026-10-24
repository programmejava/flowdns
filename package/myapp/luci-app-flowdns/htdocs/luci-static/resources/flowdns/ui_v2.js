'use strict';
'require rpc';
'require dom';

var callAction = rpc.declare({ object: 'luci.flowdns', method: 'action', params: ['name'], expect: {}, reject: true });
var callStatus = rpc.declare({ object: 'luci.flowdns', method: 'status', expect: {}, reject: true });
var actionNames = { apply: _('应用配置'), update: _('更新国内规则'), diagnose: _('完整诊断'), rollback: _('回滚规则'), stop: _('退出接管') };
var feedbackNode;

function feedback() {
	if (!feedbackNode) feedbackNode = E('div', {
		'class': 'flowdns-feedback', 'role': 'status', 'aria-live': 'polite',
		'style': 'display:none;position:static;padding:1rem;margin:1rem 0;border:1px solid currentColor;align-items:center;gap:1rem;flex-wrap:wrap'
	});
	return feedbackNode;
}

function showMessage(message, progress, ok) {
	var node = feedback();
	node.style.display = 'flex';
	node.style.borderLeft = '4px solid ' + (progress ? '#5e72e4' : ok ? '#2d8a55' : '#c0392b');
	dom.content(node, [
		E('p', { 'class': progress ? 'spinning' : '', 'style': 'flex:1;min-width:0;margin:0;white-space:pre-wrap;overflow-wrap:anywhere' }, message),
		E('button', { 'type': 'button', 'class': 'btn', 'style': 'flex:none', 'click': function(ev) {
			ev.preventDefault(); node.style.display = 'none';
		} }, progress ? _('隐藏进度（后台继续）') : _('关闭提示'))
	]);
}

function notify(result) {
	showMessage(result.message || _('操作结束。'), false, result.ok);
	return result;
}

function waitForJob(id, name) {
	showMessage((actionNames[name] || _('执行操作')) + _('：正在执行，请稍候。'), true);
	var message = feedback().firstElementChild;
	var deadline = Date.now() + 300000;
	return new Promise(function(resolve) {
		function finish(result) {
			resolve(notify(result));
		}
		function check() {
			callStatus().then(function(data) {
				if (data.ok === false) return finish(data);
				var job = data.job || {};
				if (job.id === id && job.state !== 'running' && job.state !== 'queued') {
					var result = Object.assign({}, job.result || {});
					result.ok = job.state === 'done' && result.ok !== false;
					return finish(result);
				}
				if (job.id && job.id !== id) return finish({ ok: false, message: _('任务状态已被后续操作替换，请到“状态与排查”查看结果。') });
				message.textContent = job.message || _('正在执行，请稍候。');
				if (Date.now() >= deadline) return finish({ ok: false, message: _('等待结果超时；任务可能仍在后台执行，请查看“状态与排查”。') });
				window.setTimeout(check, 1000);
			}).catch(function(error) { finish({ ok: false, message: error.message }); });
		}
		check();
	});
}

return L.Class.extend({
	feedback: feedback,
	status: function() {
		return callStatus().catch(function(error) {
			return { rpc_error: _('无法读取 FlowDNS 后端：%s。请确认已安装服务包和最新界面包；重启 rpcd 后刷新页面。终端检查命令：ubus -v list luci.flowdns').format(error.message) };
		});
	},
	explain: rpc.declare({ object: 'luci.flowdns', method: 'explain', params: ['domain'], expect: {}, reject: true }),
	commit: rpc.declare({ object: 'uci', method: 'commit', params: ['config'], reject: true }),
	action: function(name) {
		return callAction(name).then(function(result) {
			if (!result.ok) return notify(result);
			if (!result.id) return notify({ ok: false, message: _('任务未返回编号，请重新加载页面并检查界面与服务版本。') });
			return waitForJob(result.id, name);
		}).catch(function(error) {
			notify({ ok: false, message: error.message });
			throw error;
		});
	},
	setup: function(data) {
		if (data.rpc_error) return E('div', { 'class': 'alert-message warning' }, data.rpc_error);
		var links = {
			ssr_client: ['admin/services/shadowsocksr/client', _('打开 SSR Plus 客户端设置')],
			ssr_advanced: ['admin/services/shadowsocksr/advanced', _('打开 SSR Plus 高级设置')],
			passwall: ['admin/services/passwall', _('打开 PassWall')]
		};
		return E('div', { 'class': 'cbi-section' }, [E('h3', {}, _('启动前检查（按已保存配置）')),
			E('ol', {}, (data.setup || []).map(function(step) {
				var content = [E('strong', {}, (step.ready ? '✓ ' : '待完成：') + step.title), E('p', {}, step.detail)];
				if (!step.ready && links[step.link]) {
					var link = links[step.link];
					content.push(E('a', { 'class': 'btn', 'href': L.url.apply(L, link[0].split('/')) }, link[1]));
				}
				return E('li', {}, content);
			}))
		]);
	}
});
