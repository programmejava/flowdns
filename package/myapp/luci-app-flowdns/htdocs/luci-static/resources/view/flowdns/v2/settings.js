'use strict';
'require view';
'require form';
'require uci';
'require ui';
'require poll';
'require dom';
'require tools.widgets as widgets';
'require flowdns.ui_v2 as api';

return view.extend({
	load: function() { return api.status(); },
	render: function(status) {
		var m = this.map = new form.Map('flowdns', _('FlowDNS 统一分流'),
			_('国内直连，其他域名默认代理。DNS 与连接使用同一套策略；国内外上游均使用加密 DNS。'));
		var s = m.section(form.NamedSection, 'main', 'flowdns');
		s.tab('basic', _('基本设置'));
		s.tab('rules', _('手动规则'));
		s.tab('advanced', _('高级设置'));
		s.tab('help', _('操作说明'));

		var o = s.taboption('basic', form.Flag, 'enabled', _('启用统一分流'),
			_('先完成下方的代理出口设置，再启用并保存应用。国内规则首次启动时自动下载；页面会等待并显示实际执行结果。关闭后撤销接管。'));
		o.rmempty = false;
		o = s.taboption('basic', form.ListValue, 'mode', _('运行模式'),
			_('SOCKS 模式保留精确域名/Fake-IP 策略。透明代理模式仅支持 SSR Plus 的 Xray 节点，使用随服务包安装的私有 DNS 前端；代理流量直接进入独立 Xray，国内连接由内核放行。返回真实 IP，共享 IP 采用代理优先。切换后清理客户端 DNS 缓存并重开浏览器。'));
		o.value('socks', _('SOCKS 模式（原模式）'));
		o.value('transparent', _('透明代理模式（SSR Plus / Xray）'));
		o.default = 'socks'; o.rmempty = false;
		o = s.taboption('basic', form.ListValue, 'provider', _('代理来源'),
			_('PassWall：关闭主透明代理和访问控制，开启一个独立 SOCKS 服务并选好节点。SSR Plus：主服务器选“禁用”，开启本地 SOCKS5 并显式选择节点。透明代理模式另读取该 Xray 节点用于代理连接，SOCKS 供国外 DNS 使用。FlowDNS 会检查重复接管；不会自动改动代理插件。'));
		o.value('passwall', 'PassWall');
		o.value('ssrplus', 'SSR Plus');
		o.value('manual', _('手动指定本地 SOCKS5'));
		o.default = 'passwall'; o.rmempty = false;
		o = s.taboption('basic', form.ListValue, 'domestic_dns', _('国内 DNS'));
		o.value('alidns', _('阿里公共 DNS')); o.value('dnspod', _('腾讯 DNSPod'));
		o.default = 'alidns'; o.rmempty = false;
		o = s.taboption('basic', form.ListValue, 'overseas_dns', _('国外 DNS'), _('经所选代理出口查询。代理失效时，不会悄悄改为直连查询。'));
		o.value('cloudflare', 'Cloudflare'); o.value('google', 'Google');
		o.default = 'cloudflare'; o.rmempty = false;
		o = s.taboption('basic', form.ListValue, 'transport', _('加密方式'),
			_('DoH 使用 HTTPS 443；DoT 使用 TLS 853。均验证服务器证书，需要正确的系统时间。失败时不会回退到公共明文 DNS。局域网名称仍由路由器本地解析。'));
		o.value('https', 'DoH (HTTPS)'); o.value('tls', 'DoT (TLS)');
		o.default = 'https'; o.rmempty = false;
		o = s.taboption('advanced', form.Flag, 'dns_failover', _('加密 DNS 故障切换'),
			_('国内在阿里/腾讯之间切换，国外在 Google/Cloudflare 之间切换且始终经代理。连续失败 2 次才切换，冷却 3 分钟；主上游恢复后连续成功 3 次、至少 5 分钟再切回。透明模式切换仅更新 DNS 后端，保留 Xray 连接和分流集合；原 SOCKS 模式仍需重启核心。'));
		o.default = '1'; o.rmempty = false;
		o = s.taboption('advanced', form.Value, 'health_interval', _('健康检查间隔（秒）'));
		o.default = '60'; o.datatype = 'range(15,600)'; o.rmempty = false;
		o = s.taboption('advanced', form.Flag, 'auto_update', _('自动更新国内规则'),
			_('默认关闭。开启后服务运行期间按间隔下载并应用，失败保留旧版本，至少一小时后重试；更新可能短暂中断已有连接。'));
		o.default = '0'; o.rmempty = false;
		o = s.taboption('advanced', form.Value, 'update_days', _('规则更新间隔（天）'));
		o.depends('auto_update', '1'); o.default = '7'; o.datatype = 'range(1,30)'; o.rmempty = false;

		[ ['direct_domains', _('始终直连'), _('填写域名，例如 example.cn，包含其所有子域名。适用于国内网站误走代理；优先于国内域名集。')],
		  ['proxy_domains', _('始终代理'), _('适用于某个网站被错误直连。与手动直连规则重叠时，会提示冲突并拒绝应用。')],
		  ['realip_domains', _('兼容模式域名'), _('仅原 SOCKS 模式使用；透明模式本身已返回真实 IP。返回真实地址，原有直连/代理策略不变；无法恢复域名信息的连接会退到 IP 规则。')] ].forEach(function(item) {
			o = s.taboption('rules', form.DynamicList, item[0], item[1], item[2]);
			o.datatype = 'hostname';
			o.placeholder = 'example.com';
			o.validate = function(section, value) {
				if (!value) return true;
				return /^[a-zA-Z0-9][a-zA-Z0-9.-]*\.?$/.test(value) && !/^[\d.]+$/.test(value) ? true : _('只填写域名；不要填写 https://、端口、路径或通配符。中文域名请使用 Punycode。');
			};
		});

		o = s.taboption('advanced', widgets.NetworkSelect, 'networks', _('接管网络'),
			_('默认 LAN。只支持经过本路由器的受信任局域网，防火墙区域须允许输入。IPv4/IPv6 同时接管；WAN 不允许选择。路由器自身进程不在透明接管范围。'));
		o.multiple = true; o.nocreate = true; o.rmempty = false;
		o = s.taboption('advanced', form.Value, 'proxy_port', _('本地 SOCKS5 端口'), _('只接受本机 127.0.0.1 上无需认证的 SOCKS5。使用 PassWall/SSR Plus 时自动读取，此项仅用于手动模式。'));
		o.depends('provider', 'manual'); o.datatype = 'port'; o.default = '1080'; o.rmempty = false;
		o = s.taboption('advanced', form.Flag, 'udp', _('允许代理 UDP'),
			_('原模式开启时检查 SOCKS5 UDP 接口；透明代理模式由 Xray 节点承载 UDP。节点不支持时请更换节点，或关闭此项；关闭后需要代理的 UDP 会报错，国内 UDP 仍可直连。UDP 游戏和 QUIC 必须另外做实际验证。'));
		o.default = '1'; o.rmempty = false;
		o = s.taboption('advanced', form.ListValue, 'quic_policy', _('代理 QUIC 策略'),
			_('仅透明模式：自动根据所选节点处理。Vision 默认拒绝 UDP/443，FlowDNS 会提前明确拒绝，让支持回退的浏览器使用 TCP；国内直连和其它 UDP 保持原策略。强制 QUIC 应用可能无法回退。允许模式仍取决于节点支持。'));
		o.depends('mode', 'transparent'); o.value('auto', _('自动（推荐）')); o.value('reject', _('拒绝代理 QUIC，优先 TCP')); o.value('allow', _('允许代理 QUIC'));
		o.default = 'auto'; o.rmempty = false;
		o = s.taboption('advanced', form.ListValue, 'log_level', _('日志详细程度'), _('排查时可临时改为 debug。日志仅保留在内存，大小超过 1 MiB 时清空，重启后不保留。'));
		o.value('info', _('常规')); o.value('debug', _('详细')); o.value('warn', _('仅警告和错误'));
		o.default = 'info'; o.rmempty = false;

		o = s.taboption('help', form.DummyValue, '_guide', _('使用方法'));
		o.rawhtml = true;
		o.default = '<ol><li>在 PassWall 或 SSR Plus 中配置节点，启用独立 SOCKS5 出口，退出透明代理模式。</li>' +
			'<li>选择代理来源及 DNS，按照下方“启动前检查”的具体步骤配置代理插件。</li>' +
			'<li>启用 FlowDNS 并保存应用。首次启动自动下载国内规则；等待页面明确提示启动成功，提交任务本身不代表已生效。</li>' +
			'<li>在“状态与排查”运行完整诊断，再用一台设备访问国内和国外网站。</li>' +
			'<li>电脑和手机使用自动获取网络设置；Chrome 手动设置过 Google 安全 DNS 的，恢复使用系统 DNS。应用内置加密 DNS、VPN 可能绕过域名策略。</li></ol>' +
			'<p>误分流：先在诊断页查询域名，查看命中来源；再添加“始终直连”或“始终代理”，保存应用后重新打开应用。已有连接不会自动切换。</p>' +
			'<p>停用：关闭启用开关并保存应用。FlowDNS 不改写 dnsmasq 或代理插件配置。客户端缓存的 Fake-IP 可能暂时失效，必要时重启应用或重新连接网络。</p>' +
			'<p>规则更新：手动更新后保存应用；自动更新会应用新版本。数量下降超过 30% 会拒绝更新。更新不覆盖手动规则。</p>' +
			'<p>开机：服务持续等待网络、正确时间、规则和代理出口，按 2～60 秒退避重试。运行中出口中断时保留国内服务，国外不切为直连。状态页显示等待原因和健康结果。</p>' +
			'<p>性能：从项目 tools/flowdns-benchmark.py 在局域网电脑运行四模式对照；状态页“采样 CPU/内存”记录 5 秒样本。工具不会自动修改节点或路由配置。</p>' +
			'<p>透明代理模式：代理来源选 SSR Plus，继续保持 SSR 主服务器停用、独立 SOCKS 选择原 Xray 节点。FlowDNS 只读取节点并启动独立透明 Xray，不修改 SSR 配置。SOCKS 仅供国外 DNS 使用。DNS 前端随 FlowDNS 私有安装，不替换系统 dnsmasq 或 DHCP。切换后 Windows 运行 ipconfig /flushdns 并重开浏览器，手机重新连接 Wi-Fi。回退时切回 SOCKS 模式并保存应用，再清理客户端缓存。</p>' +
			'<p>透明模式边界：真实 IP 集合最长保留 24 小时，客户端 DNS TTL 上限 5 分钟；共享 CDN IP 无法精确区分域名，代理集合优先，手动直连可覆盖自动代理集合。重启/重建集合后须由客户端新查询重新学习。旧 Fake-IP 在透明模式会被拒绝，不会交给 Xray。HTTPS/SVCB DNS 记录在该模式过滤，HTTP/3 仍需实际验证。</p>';

		var setup = E('div'), rulesInfo = E('p');
		function update(data) {
			dom.content(setup, api.setup(data));
			rulesInfo.textContent = _('国内域名：%s 条；可用规则版本：%s。').format(data.domain_count || 0, data.rules_version || _('尚未初始化，首次启用时自动下载'));
		}
		update(status);
		poll.add(function() { return api.status().then(update); }, 3);
		var buttons = E('div', { 'class': 'cbi-section' }, [
			rulesInfo,
			E('button', { 'class': 'btn cbi-button-action', 'click': function() { return api.action('update'); } }, _('更新国内规则')),
			' ', E('a', { 'class': 'btn', 'href': L.url('admin/services/flowdns/diagnostics') }, _('查看状态与排查'))
		]);
		return m.render().then(function(node) {
			return E('div', {}, [api.feedback(), setup, node, buttons]);
		});
	},
	handleSaveApply: function() {
		return this.map.save().then(function() { return uci.save(); })
			.then(function() { return api.commit('flowdns'); })
			.then(function() { return api.action('apply'); });
	},
	handleSave: null,
	handleReset: function() { window.location.reload(); }
});
