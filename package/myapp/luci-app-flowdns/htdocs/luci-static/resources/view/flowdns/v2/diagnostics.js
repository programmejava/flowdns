'use strict';
'require view';
'require poll';
'require dom';
'require flowdns.ui_v2 as api';

return view.extend({
	load: function() { return api.status(); },
	render: function(initial) {
		var self = this;
		var summary = E('div'), setup = E('div'), results = E('div'), job = E('p'), error = E('pre', { 'style': 'white-space:pre-wrap' });
		var logs = E('pre', { 'style': 'max-height:420px;overflow:auto;white-space:pre-wrap;overflow-wrap:anywhere' });
		var startup = E('pre', { 'style': 'max-height:260px;overflow:auto;white-space:pre-wrap;overflow-wrap:anywhere' });
		var counters = E('pre', { 'style': 'max-height:260px;overflow:auto;white-space:pre-wrap' });
		var health = E('div'), maintenance = E('pre', { 'style': 'max-height:360px;overflow:auto;white-space:pre-wrap' });
		var recent = E('pre', { 'style': 'max-height:260px;overflow:auto;white-space:pre-wrap' });
		var input = E('input', { 'class': 'cbi-input-text', 'placeholder': 'www.example.com', 'maxlength': 253 });
		var decision = E('div'), buttons = [];
		function action(label, name) {
			var b = E('button', { 'type': 'button', 'class': 'btn cbi-button-action', 'click': function() { return api.action(name); } }, label);
			buttons.push(b); return b;
		}
		function update(data) {
			self.lastReport = data;
			dom.content(setup, api.setup(data));
			var active = data.active || {};
			var exit = !active.provider ? _('尚未应用') : active.mode === 'transparent'
				? 'Xray · ' + (active.ssr_node || 'SSR Plus') + '；' + _('国外 DNS 使用 SOCKS') + ' 127.0.0.1:' + active.proxy_port
				: active.provider + ' · 127.0.0.1:' + active.proxy_port;
			dom.content(summary, E('table', { 'class': 'table' }, [
				E('tr', { 'class': 'tr' }, [E('td', { 'class': 'td' }, _('当前运行模式')), E('td', { 'class': 'td' }, (active.mode || data.mode) === 'transparent' ? _('透明代理（SSR Plus / Xray）') : _('SOCKS / Fake-IP'))]),
				E('tr', { 'class': 'tr' }, [E('td', { 'class': 'td' }, _('核心进程')), E('td', { 'class': 'td' }, data.rpc_error ? _('后端不可用') : data.state === 'waiting' ? _('等待依赖，自动重试') : data.dns_updating ? _('DNS 更新中，代理连接保持') : data.starting ? _('启动中（核心最多等待 90 秒）') : data.state === 'degraded' ? _('运行中，部分链路异常') : data.running ? _('运行中') : data.state === 'failed' ? _('启动或接管失败') : _('未运行'))]),
				E('tr', { 'class': 'tr' }, [E('td', { 'class': 'td' }, _('DNS / 防火墙')), E('td', { 'class': 'td' }, (data.dns_ready ? _('监听就绪') : _('未监听')) + ' / ' + (data.attached ? _('已接管') : _('未接管')))]),
				E('tr', { 'class': 'tr' }, [E('td', { 'class': 'td' }, _('国外出口验证')), E('td', { 'class': 'td' }, data.egress_ready ? _('加密 DNS 及代理出口已验证') : data.running ? _('恢复中，后台快速检查；国内服务保持') : _('等待核心启动'))]),
				E('tr', { 'class': 'tr' }, [E('td', { 'class': 'td' }, _('当前有效出口')), E('td', { 'class': 'td' }, exit)]),
				E('tr', { 'class': 'tr' }, [E('td', { 'class': 'td' }, _('当前有效 DNS')), E('td', { 'class': 'td' }, active.transport ? (active.domestic_active || active.domestic_dns) + ' / ' + (active.overseas_active || active.overseas_dns) + ' · ' + (active.transport === 'tls' ? 'DoT' : 'DoH') : _('尚未应用'))]),
				E('tr', { 'class': 'tr' }, [E('td', { 'class': 'td' }, _('代理 QUIC')), E('td', { 'class': 'td' }, active.mode === 'transparent' ? (active.quic_effective === 'reject' ? _('提前拒绝 UDP/443，其它 UDP 保持原策略') : _('允许，由节点承载')) : _('由原 SOCKS 出口处理'))]),
				E('tr', { 'class': 'tr' }, [E('td', { 'class': 'td' }, _('有效 / 可用规则版本')), E('td', { 'class': 'td' }, (active.rules_version || '—') + ' / ' + (data.rules_version || '—'))])
			]));
			var task = data.job || {};
			job.textContent = task.state ? _('最近操作：%s · %s').format(task.action, (task.state === 'running' || task.state === 'queued') ? _('进行中') : task.state === 'done' ? _('完成') : _('失败')) + '\n' + ((task.result || {}).message || '') : _('尚未执行操作。');
			buttons.forEach(function(b) { b.disabled = (task.state === 'running' || task.state === 'queued') || !!data.rpc_error; });
			error.textContent = data.rpc_error || data.error || '';
			var checks = data.checks || {};
			dom.content(results, [
				E('p', {}, checks.time ? _('上次诊断：%s；诊断结果不会随设置自动刷新，请应用后重新运行。').format(new Date(checks.time * 1000).toLocaleString()) : _('尚未诊断。点击“运行完整诊断”逐项检查。')),
				E('table', { 'class': 'table' }, (checks.items || []).map(function(item) {
					return E('tr', { 'class': 'tr' }, [
						E('td', { 'class': 'td' }, (item.state === 'ok' ? '✓ ' : item.state === 'error' ? '✗ ' : '△ ') + item.name),
						E('td', { 'class': 'td', 'style': 'white-space:pre-wrap' }, item.detail)
					]);
				}))
			]);
			logs.textContent = data.log || _('暂无日志。启用后从客户端发起访问，或运行诊断。');
			startup.textContent = (data.startup_log || '') + '\n' + (data.dns_reload_log || '');
			var h = data.health || {}, groups = h.groups || {}, sw = data.dns_switch || {};
			dom.content(health, [E('p', {}, data.waiting || h.message || _('等待首次健康检查。')),
				E('p', {}, _('国内：%s；国外：%s。').format((groups.domestic || {}).active || active.domestic_active || active.domestic_dns || '—', (groups.overseas || {}).active || active.overseas_active || active.overseas_dns || '—')),
				E('p', {}, sw.state ? _('最近 DNS 更新：%s；耗时 %s 毫秒。%s').format(sw.state === 'done' ? _('完成') : sw.state === 'rolled-back' ? _('已回退') : _('失败'), sw.elapsed_ms || 0, sw.message || '') + ' ' + (((sw.from || {}).domestic || '—') + ' / ' + ((sw.from || {}).overseas || '—') + ' → ' + ((sw.to || {}).domestic || '—') + ' / ' + ((sw.to || {}).overseas || '—')) : '')]);
			maintenance.textContent = JSON.stringify({ rules: data.rules, update: data.update, environment: data.environment, timing: data.timing, operation: data.operation, dns_switch: data.dns_switch, metrics: data.metrics }, null, 2);
			recent.textContent = data.recent_errors || _('近期无错误日志。');
			counters.textContent = data.firewall || _('尚无接管计数器。');
		}
		var query = E('button', { 'type': 'button', 'class': 'btn cbi-button-action', 'click': function() {
			query.disabled = true;
			return api.explain(input.value.trim()).then(function(r) {
				if (r.ok === false) { dom.content(decision, E('p', {}, r.message)); return; }
				var labels = { direct: _('直连'), proxy: _('代理'), local: _('局域网解析') };
				dom.content(decision, [
					E('p', {}, r.domain + ' → ' + (labels[r.action] || r.action)),
					E('p', {}, _('依据：%s；命中：%s；DNS：%s；地址模式：%s。').format(r.reason, r.matched || '—', r.dns, r.fakeip ? 'Fake-IP' : _('真实地址'))),
					E('p', {}, r.scope + ' · ' + r.note)
				]);
			}).catch(function(e) { dom.content(decision, E('p', {}, e.message)); })
				.finally(function() { query.disabled = false; });
		} }, _('查询分流原因'));
		input.addEventListener('keydown', function(e) { if (e.key === 'Enter') query.click(); });
		var report = E('button', { 'type': 'button', 'class': 'btn', 'click': function() {
			var data = Object.assign({}, self.lastReport);
			// No subscription or node credentials are collected. Logs can contain browsing domains.
			delete data.active;
			var url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' }));
			var a = E('a', { 'href': url, 'download': 'flowdns-diagnostics.json' });
			a.click(); window.setTimeout(function() { URL.revokeObjectURL(url); }, 1000);
		} }, _('导出诊断报告'));
		update(initial);
		poll.add(function() { return api.status().then(update).catch(function(e) {
			error.textContent = _('无法读取后端状态：%s。请检查 rpcd 服务与 FlowDNS 安装是否完整。').format(e.message);
		}); }, 3);
		return E('div', {}, [
			E('h2', {}, _('FlowDNS 状态与排查')), api.feedback(), summary, setup,
			E('h3', {}, _('运行健康')), health,
			E('div', { 'class': 'cbi-section' }, [action(_('运行完整诊断'), 'diagnose'), ' ', action(_('采样 CPU/内存'), 'sample'), ' ', action(_('检查兼容环境'), 'environment'), ' ', action(_('更新国内规则'), 'update'), ' ', action(_('回滚规则版本'), 'rollback'), ' ', action(_('暂时退出接管'), 'stop'), ' ', report, job, error]),
			E('h3', {}, _('域名策略查询')), E('p', {}, _('只填写域名，例如 www.qq.com。这里展示策略预判；实际是否命中请结合核心日志。')), input, ' ', query, decision,
			E('h3', {}, _('逐项诊断')), results,
			E('p', {}, _('以上为路由器自检；电脑和手机请使用系统 DNS，再验证实际网页访问。浏览器单独指定安全 DNS 时可能绕过统一域名策略。')),
			E('p', {}, _('导出的报告含域名和可能的局域网地址，分享前请检查。')),
			E('h3', {}, _('核心日志')), logs,
			E('h3', {}, _('近期错误')), recent,
			E('details', {}, [E('summary', {}, _('规则来源、更新差异、运行环境和性能样本')), maintenance]),
			E('details', {}, [E('summary', {}, _('启动日志（核心标准输出与错误）')), startup]),
			E('details', {}, [E('summary', {}, _('防火墙计数器')), E('p', {}, _('从客户端访问网站后，DNS/流量计数应增加。IPv6 与 IPv4 分别检查；零计数通常表示设备未经过所选网络，或使用了其他 DNS/VPN。')), counters])
		]);
	},
	handleSave: null,
	handleSaveApply: null,
	handleReset: null
});
