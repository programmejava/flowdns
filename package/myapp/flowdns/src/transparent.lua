-- SPDX-License-Identifier: GPL-3.0-or-later
-- SSR/Xray transparent data plane. No credentials are stored in UCI by us.
local M = {}
M.sets = { 'manual_proxy', 'manual_direct', 'foreign', 'domestic' }
local function clone(t)
	if type(t) ~= 'table' then return t end
	local out = {}; for key, value in pairs(t) do out[key] = clone(value) end; return out
end

function M.xray(c, generated)
	assert(type(generated) == 'table' and type(generated.outbounds) == 'table', 'SSR 配置生成器未返回有效 Xray 配置。')
	local supported = { vless = true, vmess = true, trojan = true, shadowsocks = true }
	local outbounds, candidates, selected, tags = clone(generated.outbounds), {}, {}, {}
	for _, outbound in ipairs(outbounds) do
		if type(outbound.tag) == 'string' and outbound.tag ~= '' then tags[outbound.tag] = true end
		if supported[outbound.protocol] then
			candidates[#candidates + 1] = outbound
			-- This repository tags the main node as section-id[:alias]. Other
			-- SSR releases may put direct first or omit the proxy tag entirely.
			if c.ssr_node and type(outbound.tag) == 'string' and
				(outbound.tag == c.ssr_node or outbound.tag:sub(1, #c.ssr_node + 1) == c.ssr_node .. ':') then
				selected[#selected + 1] = outbound
			end
		end
	end
	assert(#candidates > 0, 'SSR 生成配置中没有受支持的代理出站；透明模式需要 VLESS/VMess/Trojan/Shadowsocks Xray 节点。')
	local primary = #selected == 1 and selected[1] or (#candidates == 1 and candidates[1])
	assert(primary, 'SSR 生成了多个代理出站，无法唯一确定所选节点；保留原模式，请检查 SSR 生成器兼容性。')
	if type(primary.tag) ~= 'string' or primary.tag == '' then
		local name, suffix = 'flowdns-node', 0
		while tags[name] do suffix = suffix + 1; name = 'flowdns-node-' .. suffix end
		primary.tag = name
	end
	local vision = primary.protocol == 'vless' and ((((primary.settings or {}).vnext or {})[1] or {}).users or {})[1]
	local blocks = vision and vision.flow == 'xtls-rprx-vision'
	c.quic_effective = (c.quic_policy == 'reject' or (c.quic_policy ~= 'allow' and blocks)) and 'reject' or 'allow'
	-- Explicit allow uses Xray's documented client-only UDP443 flow variant.
	if c.quic_policy == 'allow' and blocks then vision.flow = 'xtls-rprx-vision-udp443' end
	c.quic_reason = c.quic_policy == 'auto' and (blocks and 'Vision 节点默认拒绝 QUIC，在路由层提前拒绝' or '节点未声明拒绝 QUIC，保持原有 UDP 路径') or '手动策略'
	local result = {
		log = { loglevel = c.log_level == 'warn' and 'warning' or c.log_level, error = '/var/run/flowdns/xray.log' },
		inbounds = { { tag = 'flowdns-transparent', listen = '::', port = 15355, protocol = 'dokodemo-door',
			settings = { network = c.udp and 'tcp,udp' or 'tcp', followRedirect = true },
			streamSettings = { sockopt = { tproxy = 'tproxy' } }, sniffing = { enabled = false } } },
		outbounds = outbounds,
		routing = { domainStrategy = 'AsIs', rules = { { type = 'field', inboundTag = { 'flowdns-transparent' }, outboundTag = primary.tag } } }
	}
	-- Keep the node's transport/Reality/Mux/fragment outbounds. Deliberately do
	-- not inherit the plugin's DNS or routing rules: FlowDNS owns the policy.
	return clone(result)
end

function M.dnsmasq(c, domains)
	local lines = { 'port=16553', 'no-resolv', 'no-hosts', 'bind-interfaces', 'interface=lo',
		'server=127.0.0.1#16554', 'cache-size=0', 'max-ttl=300', 'edns-packet-max=1232',
		'user=root', 'group=root', 'pid-file=/var/run/flowdns/front.pid', 'log-facility=/var/run/flowdns/dnsmasq.log', 'log-async=25',
		'filter-rr=HTTPS,SVCB' }
	for _, dev in ipairs(c.devices) do
		assert(dev:match('^[%w_.:%-]+$') and #dev <= 15 and dev ~= 'lo', '无效 LAN 接口。')
		lines[#lines + 1] = 'interface=' .. dev
	end
	local function add(domain, set)
		lines[#lines + 1] = 'nftset=/' .. domain .. '/4#inet#flowdns#' .. set .. '4,6#inet#flowdns#' .. set .. '6'
	end
	add('#', 'foreign')
	for _, domain in ipairs(domains) do add(domain, 'domestic') end
	for _, domain in ipairs(c.direct_domains) do add(domain, 'manual_direct') end
	for _, domain in ipairs(c.proxy_domains) do add(domain, 'manual_proxy') end
	-- Local names still use the router's resolver; their private answers are
	-- bypassed before public sets are consulted.
	for _, domain in ipairs(c.local_domains) do add(domain, 'domestic') end
	return table.concat(lines, '\n') .. '\n'
end

function M.firewall(c, cidrs, core)
	local out, devices, ip4, ip6 = {}, {}, {}, {}
	for _, dev in ipairs(c.devices) do
		assert(dev:match('^[%w_.:%-]+$') and #dev <= 15 and dev ~= 'lo', '无效 LAN 接口。')
		devices[#devices + 1] = '"' .. dev .. '"'
	end
	assert(#devices > 0, '没有 LAN 接口。')
	devices = table.concat(devices, ', ')
	for _, cidr in ipairs(cidrs) do
		local family = cidr:find(':', 1, true) and 6 or 4
		assert(core.cidr(cidr, family), '国内 IP 数据损坏。')
		local list = family == 4 and ip4 or ip6; list[#list + 1] = cidr
	end
	out[#out + 1] = 'table inet flowdns {'
	for _, family in ipairs({ 4, 6 }) do
		for _, name in ipairs(M.sets) do
			out[#out + 1] = ('set %s%d { type ipv%d_addr; flags timeout; timeout 24h; gc-interval 1m; size 131072; }'):format(name, family, family)
		end
		local ips = family == 4 and ip4 or ip6
		out[#out + 1] = ('set china%d { type ipv%d_addr; flags interval; auto-merge; %s }'):format(family, family,
			#ips > 0 and ('elements = { ' .. table.concat(ips, ', ') .. ' };') or '')
	end
	out[#out + 1] = ('chain guard { type filter hook input priority -10; policy accept; iifname "lo" return; iifname != { %s } meta l4proto { tcp, udp } th dport { 16553, 16554, 15355 } counter drop; }'):format(devices)
	out[#out + 1] = ('chain dns { type nat hook prerouting priority -110; policy accept; iifname { %s } meta l4proto { tcp, udp } th dport 53 counter redirect to :16553; }'):format(devices)
	out[#out + 1] = 'chain proxy {'
	if c.udp and (c.quic_effective == 'reject' or c.quic_policy == 'reject') then out[#out + 1] = 'udp dport 443 counter reject with icmpx type port-unreachable;' end
	if not c.udp then out[#out + 1] = 'meta l4proto udp counter reject;' end
	out[#out + 1] = 'meta l4proto { tcp, udp } meta mark set meta mark | 0x40000000 counter tproxy to :15355 accept; }'
	out[#out + 1] = 'chain traffic { type filter hook prerouting priority -150; policy accept;'
	out[#out + 1] = ('iifname != { %s } return; meta l4proto != { tcp, udp } return; th dport 53 return;'):format(devices)
	-- A previous mode's Fake-IP is never sent to Xray as a public destination.
	out[#out + 1] = 'ip daddr 198.18.0.0/15 counter reject; ip6 daddr fc00::/18 counter reject;'
	out[#out + 1] = 'fib daddr type local return;'
	out[#out + 1] = 'ip daddr { 0.0.0.0/8, 10.0.0.0/8, 127.0.0.0/8, 169.254.0.0/16, 172.16.0.0/12, 192.168.0.0/16, 224.0.0.0/4, 240.0.0.0/4 } return;'
	out[#out + 1] = 'ip6 daddr { ::/128, ::1/128, fc00::/7, fe80::/10, ff00::/8 } return;'
	for _, entry in ipairs({ { 'manual_proxy', 'jump proxy' }, { 'manual_direct', 'return' }, { 'foreign', 'jump proxy' }, { 'domestic', 'return' } }) do
		out[#out + 1] = ('ip daddr @%s4 counter %s; ip6 daddr @%s6 counter %s;'):format(entry[1], entry[2], entry[1], entry[2])
	end
	out[#out + 1] = 'ip daddr @china4 counter return; ip6 daddr @china6 counter return;'
	out[#out + 1] = 'jump proxy; }\n}'
	return table.concat(out, '\n') .. '\n'
end

function M.equal(a, b, skip)
	if type(a) ~= type(b) then return false end
	if type(a) ~= 'table' then return a == b end
	for k,v in pairs(a) do if not (skip and skip[k]) and not M.equal(v, b[k]) then return false end end
	for k,v in pairs(b) do if not (skip and skip[k]) and a[k] == nil then return false end end
	return true
end
function M.dns_only(a, b)
	return a and b and a.mode == 'transparent' and b.mode == 'transparent'
		and M.equal(a,b,{ domestic_dns=true,overseas_dns=true,domestic_active=true,overseas_active=true,transport=true })
end
return M
