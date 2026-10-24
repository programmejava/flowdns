-- SPDX-License-Identifier: GPL-3.0-or-later
-- Pure policy compiler: shared by configuration generation and diagnostics.
local M = {}
M.dns_port = 16553
M.dns_backend_port = 16554
M.tproxy_port = 15355
M.startup_timeout = 90
M.mark = '0x40000000'
M.table_id = 20260

-- ip -N -j uses numeric strings for table IDs and route types. Do not infer
-- ownership from a display line: table names, default prefixes and errors vary.
function M.owns_rule(rule)
	local allowed = { priority = true, src = true, dst = true, table = true,
		fwmark = true, fwmask = true, protocol = true, flags = true }
	for key in pairs(rule) do if not allowed[key] then return false end end
	local function all(value) return value == nil or value == 'all' or value == '0.0.0.0/0' or value == '::/0' end
	return tonumber(rule.priority) == M.table_id and tonumber(rule.table) == M.table_id
		and tonumber(rule.fwmark) == tonumber(M.mark) and tonumber(rule.fwmask) == tonumber(M.mark)
		and all(rule.src) and all(rule.dst) and (not rule.flags or #rule.flags == 0)
end

function M.owns_route(route)
	return tonumber(route.table) == M.table_id and (route.type == 'local' or tonumber(route.type) == 2)
		and (route.dst == 'default' or route.dst == '0.0.0.0/0' or route.dst == '::/0')
		and route.dev == 'lo' and not route.gateway and not route.via and not route.nexthops
		and not route.encap and not route.prefsrc and not route.from
end

M.providers = {
	alidns = { ip = '223.5.5.5', name = 'dns.alidns.com' },
	dnspod = { ip = '1.12.12.12', name = 'dot.pub', https_name = 'doh.pub' },
	google = { ip = '8.8.8.8', name = 'dns.google' },
	cloudflare = { ip = '1.1.1.1', name = 'cloudflare-dns.com', tls_name = 'one.one.one.one' }
}

function M.domain(value)
	if type(value) ~= 'string' then return nil end
	local d = value:lower():match('^%s*(.-)%s*$'):gsub('%.$', '')
	if #d < 1 or #d > 253 or not d:match('^[a-z0-9][a-z0-9.%-]*$') then return nil end
	if d:match('^[%d.]+$') then return nil end
	for label in (d .. '.'):gmatch('(.-)%.') do
		if #label == 0 or #label > 63 or label:match('^%-') or label:match('%-$') then return nil end
	end
	return d
end

function M.matches(domain, suffix)
	return domain == suffix or domain:sub(-#suffix - 1) == '.' .. suffix
end

function M.domains(values)
	local out, seen = {}, {}
	if type(values) == 'string' then values = { values } end
	for _, value in ipairs(values or {}) do
		local d = M.domain(value)
		assert(d, '无效域名：' .. tostring(value) .. '。请只填写域名，不要填写网址、端口或通配符。')
		if not seen[d] then out[#out + 1], seen[d] = d, true end
	end
	table.sort(out)
	return out
end

function M.validate(c)
	c.mode = c.mode or 'socks'
	c.quic_policy = c.quic_policy or 'auto'
	assert(c.quic_policy == 'auto' or c.quic_policy == 'reject' or c.quic_policy == 'allow', '无效的代理 QUIC 策略。')
	assert(c.mode == 'socks' or c.mode == 'transparent', '无效的运行模式。')
	assert(c.mode ~= 'transparent' or c.provider == 'ssrplus', '透明代理模式目前只支持 SSR Plus 的 Xray 节点。')
	assert(c.provider == 'passwall' or c.provider == 'ssrplus' or c.provider == 'manual', '请选择有效的代理来源。')
	assert(c.transport == 'https' or c.transport == 'tls', '加密 DNS 只支持 DoH 或 DoT。')
	assert(c.domestic_dns == 'alidns' or c.domestic_dns == 'dnspod', '请选择国内 DNS。')
	assert(c.overseas_dns == 'google' or c.overseas_dns == 'cloudflare', '请选择国外 DNS。')
	c.dns_failover = c.dns_failover ~= '0' and c.dns_failover ~= false
	c.auto_update = c.auto_update == '1' or c.auto_update == true
	c.health_interval = tonumber(c.health_interval or 60)
	assert(c.health_interval and c.health_interval >= 15 and c.health_interval <= 600 and c.health_interval % 1 == 0, '健康检查间隔必须为 15–600 秒。')
	c.update_days = tonumber(c.update_days or 7)
	assert(c.update_days and c.update_days >= 1 and c.update_days <= 30 and c.update_days % 1 == 0, '规则更新间隔必须为 1–30 天。')
	c.proxy_port = tonumber(c.proxy_port)
	assert(c.proxy_port and c.proxy_port >= 1 and c.proxy_port <= 65535 and c.proxy_port % 1 == 0, '本地 SOCKS5 端口必须为 1–65535。')
	assert(c.proxy_port ~= M.dns_port and c.proxy_port ~= M.tproxy_port and c.proxy_port ~= M.dns_backend_port, '代理端口与 FlowDNS 内部端口冲突。')
	c.direct_domains, c.proxy_domains = M.domains(c.direct_domains), M.domains(c.proxy_domains)
	c.realip_domains = M.domains(c.realip_domains)
	for _, a in ipairs(c.direct_domains) do
		for _, b in ipairs(c.proxy_domains) do
			assert(not M.matches(a, b) and not M.matches(b, a), '直连与代理规则重叠：' .. a .. ' / ' .. b .. '。请删除冲突后再应用。')
		end
	end
	assert(c.log_level == 'info' or c.log_level == 'debug' or c.log_level == 'warn', '无效的日志级别。')
	return c
end

function M.parse_china(text)
	local list = {}
	for line in text:gmatch('[^\r\n]+') do
		local d = line:match('^server=/([^/]+)/')
		if d then list[#list + 1] = d end
	end
	return M.domains(list)
end

function M.cidr(value, family)
	local ip, bits = value:match('^([^/]+)/(%d+)$')
	bits = tonumber(bits)
	if not ip or not bits then return false end
	if family == 4 then
		if bits < 1 or bits > 32 then return false end
		local count = 0
		for part in (ip .. '.'):gmatch('(.-)%.') do
			if not part:match('^%d+$') or #part > 3 or tonumber(part) > 255 then return false end
			count = count + 1
		end
		return count == 4
	end
	if bits < 1 or bits > 128 or not ip:find(':') or ip:find('[^%x:]') then return false end
	local _, doubles = ip:gsub('::', '')
	if doubles > 1 or ip:find(':::') then return false end
	if doubles == 0 and (ip:sub(1, 1) == ':' or ip:sub(-1) == ':') then return false end
	local count = 0
	for part in ip:gmatch('[^:]+') do
		if #part > 4 then return false end
		count = count + 1
	end
	return (doubles == 0 and count == 8) or (doubles == 1 and count < 8)
end

function M.parse_cidrs(text, family)
	local out, seen = {}, {}
	for line in text:gmatch('[^\r\n]+') do
		line = line:match('^%s*(.-)%s*$')
		if line ~= '' and not line:match('^#') then
			assert(M.cidr(line, family), 'IP 规则数据不合法：' .. line)
			if not seen[line] then out[#out + 1], seen[line] = line, true end
		end
	end
	return out
end

function M.reverse_domains()
	local reverse = { '0.in-addr.arpa', '10.in-addr.arpa', '127.in-addr.arpa', '254.169.in-addr.arpa', '168.192.in-addr.arpa',
		'c.f.ip6.arpa', 'd.f.ip6.arpa', '8.e.f.ip6.arpa', '9.e.f.ip6.arpa', 'a.e.f.ip6.arpa', 'b.e.f.ip6.arpa',
		'1.' .. string.rep('0.', 31) .. 'ip6.arpa' }
	for n = 16, 31 do reverse[#reverse + 1] = n .. '.172.in-addr.arpa' end
	return reverse
end

function M.classify(c, rules, name)
	local d = assert(M.domain(name), '请输入有效域名，例如 www.example.com。')
	for _, suffix in ipairs(c.local_domains or { 'lan', 'local', 'home.arpa' }) do
		if M.matches(d, suffix) then return { domain = d, action = 'local', reason = '局域网域名', dns = '路由器本地解析', fakeip = false } end
	end
	for _, suffix in ipairs(M.reverse_domains()) do
		if M.matches(d, suffix) then return { domain = d, action = 'local', reason = '私有地址反向解析', dns = '路由器本地解析', fakeip = false } end
	end
	local result = { domain = d, action = 'proxy', reason = '未命中直连规则，默认代理', dns = c.overseas_dns, fakeip = true }
	for _, item in ipairs({ { c.direct_domains, 'direct', '手动直连' }, { c.proxy_domains, 'proxy', '手动代理' }, { rules.domains, 'direct', '国内域名集' } }) do
		for _, suffix in ipairs(item[1] or {}) do
			if M.matches(d, suffix) then
				result.action, result.reason, result.matched = item[2], item[3], suffix
				result.dns, result.fakeip = item[2] == 'direct' and c.domestic_dns or c.overseas_dns, item[2] == 'proxy'
				break
			end
		end
		if result.matched then break end
	end
	for _, suffix in ipairs(c.realip_domains) do if M.matches(d, suffix) then result.fakeip = false end end
	if c.mode == 'transparent' then
		result.fakeip = false
		result.note = '透明模式以 DNS 学习的真实 IP 集合路由；共享 IP 无法区分域名，代理集合优先。'
	end
	return result
end

function M.dns_server(c, id, tag, proxy)
	local p = M.providers[id]
	local name = c.transport == 'https' and (p.https_name or p.name) or (p.tls_name or p.name)
	local s = { type = c.transport, tag = tag, server = p.ip, server_port = c.transport == 'https' and 443 or 853,
		tls = { enabled = true, server_name = name }, detour = proxy and 'proxy' or 'direct' }
	if c.transport == 'https' then s.path, s.headers = '/dns-query', { Host = name } end
	return s
end

function M.config(c, rules_path)
	-- luci.jsonc treats a second reference to the same table as a cycle and
	-- emits null. Each occurrence of a match list must have its own identity.
	local function tree(value)
		if type(value) ~= 'table' then return value end
		local out = {}
		for key, item in pairs(value) do out[key] = tree(item) end
		return out
	end
	local dns_rules = {
		{ domain_suffix = c.local_domains, action = 'route', server = 'local' },
		{ domain_suffix = M.reverse_domains(), action = 'route', server = 'local' }
	}
	local route_rules = {
		{ inbound = { 'dns-in' }, action = 'hijack-dns' },
		{ action = 'sniff', timeout = '300ms' },
		{ protocol = 'dns', action = 'hijack-dns' },
		{ domain_suffix = c.local_domains, action = 'route', outbound = 'direct' }
	}
	local function policy(match, action, fake)
		local rr, dr = {}, {}
		for k, v in pairs(match) do rr[k], dr[k] = v, v end
		if action == 'proxy' then
			local resolve = {}
			for k, v in pairs(match) do resolve[k] = v end
			resolve.action, resolve.server = 'resolve', 'overseas'
			route_rules[#route_rules + 1] = resolve
		end
		rr.action, rr.outbound = 'route', action
		route_rules[#route_rules + 1] = rr
		if fake and c.mode ~= 'transparent' then
			local fr = {}
			for k, v in pairs(match) do fr[k] = v end
			fr.query_type = { 'A', 'AAAA' }
			if #c.realip_domains > 0 then
				fr = { type = 'logical', mode = 'and', rules = { fr, { domain_suffix = c.realip_domains, invert = true } } }
			end
			fr.action, fr.server = 'route', 'fakeip'
			dns_rules[#dns_rules + 1] = fr
		end
		dr.action, dr.server = 'route', action == 'direct' and 'domestic' or 'overseas'
		dns_rules[#dns_rules + 1] = dr
	end
	if #c.direct_domains > 0 then policy({ domain_suffix = c.direct_domains }, 'direct', false) end
	if #c.proxy_domains > 0 then policy({ domain_suffix = c.proxy_domains }, 'proxy', true) end
	policy({ rule_set = { 'china-domains' } }, 'direct', false)
	local fallback = { query_type = { 'A', 'AAAA' } }
	if #c.realip_domains > 0 then fallback = { type = 'logical', mode = 'and', rules = { fallback, { domain_suffix = c.realip_domains, invert = true } } } end
	fallback.action, fallback.server = 'route', 'fakeip'
	if c.mode ~= 'transparent' then dns_rules[#dns_rules + 1] = fallback end
	-- A known domain's decision must not be overridden by its CDN's IP country.
	route_rules[#route_rules + 1] = { domain_regex = { '.+' }, action = 'resolve', server = 'overseas' }
	route_rules[#route_rules + 1] = { domain_regex = { '.+' }, action = 'route', outbound = 'proxy' }
	route_rules[#route_rules + 1] = { ip_is_private = true, action = 'route', outbound = 'direct' }
	route_rules[#route_rules + 1] = { rule_set = { 'china-ip' }, action = 'route', outbound = 'direct' }
	if not c.udp then route_rules[#route_rules + 1] = { network = 'udp', action = 'reject' } end
	local result = {
		log = { level = c.log_level, timestamp = true, output = '/var/run/flowdns/core.log' },
		dns = { servers = {
			M.dns_server(c, c.domestic_active or c.domestic_dns, 'domestic', false), M.dns_server(c, c.overseas_active or c.overseas_dns, 'overseas', true),
			{ type = 'udp', tag = 'local', server = '127.0.0.1', server_port = c.local_dns_port },
			{ type = 'fakeip', tag = 'fakeip', inet4_range = '198.18.0.0/15', inet6_range = 'fc00::/18' }
		}, rules = dns_rules, final = 'overseas', independent_cache = true, reverse_mapping = true },
		inbounds = {
			{ type = 'direct', tag = 'dns-in', listen = '::', listen_port = M.dns_port },
			{ type = 'tproxy', tag = 'tproxy-in', listen = '::', listen_port = M.tproxy_port }
		},
		outbounds = {
			{ type = 'direct', tag = 'direct', domain_resolver = 'domestic' },
			{ type = 'socks', tag = 'proxy', server = '127.0.0.1', server_port = c.proxy_port, version = '5', network = c.udp and { 'tcp', 'udp' } or 'tcp' }
		},
		route = { rules = route_rules, final = 'proxy', default_domain_resolver = 'overseas', rule_set = {
			{ type = 'local', tag = 'china-domains', format = c.binary_rules and 'binary' or 'source', path = rules_path .. (c.binary_rules and '/domains.srs' or '/domains.json') },
			{ type = 'local', tag = 'china-ip', format = c.binary_rules and 'binary' or 'source', path = rules_path .. (c.binary_rules and '/ip.srs' or '/ip.json') }
		} },
		experimental = { cache_file = { enabled = true, path = '/etc/flowdns/cache.db', store_fakeip = true } }
	}
	if c.mode == 'transparent' then
		result.inbounds = { { type = 'direct', tag = 'dns-in', listen = '127.0.0.1', listen_port = M.dns_backend_port } }
		result.route.rules = { { inbound = { 'dns-in' }, action = 'hijack-dns' } }
		-- This process handles DNS only. Real client connections enter Xray.
		table.remove(result.dns.servers, 4)
		result.experimental.cache_file.store_fakeip = false
	end
	return tree(result)
end

function M.backup(id)
	return ({ alidns = 'dnspod', dnspod = 'alidns', google = 'cloudflare', cloudflare = 'google' })[id]
end

-- Sticky failover: two failures, a verified backup, and a three-minute
-- cooldown. Failback requires three healthy primary checks after five minutes.
function M.dns_health(previous, primary, active, active_ok, primary_ok, backup_ok, now, enabled, recovering)
	local s = { active = active, failures = active_ok and 0 or ((previous.failures or 0) + 1),
		successes = primary_ok and ((previous.successes or 0) + 1) or 0,
		switched = previous.switched or 0 }
	-- A verified live backup must not be blocked by the failback cooldown when
	-- the active DNS is dead. Recovery uses one failure; steady state uses two.
	if enabled and not active_ok and s.failures >= (recovering and 1 or 2) then
		local other = active == primary and M.backup(primary) or primary
		if (other == primary and primary_ok) or (other ~= primary and backup_ok) then
			s.active, s.switched, s.failures, s.successes = other, now, 0, 0
		end
	elseif enabled and active ~= primary and s.successes >= 3 and now - s.switched >= 300 then
		s.active, s.switched, s.failures, s.successes = primary, now, 0, 0
	end
	return s
end

function M.rule_change(old, new)
	local changes = {}
	for _, key in ipairs({ 'domain_count', 'ipv4_count', 'ipv6_count' }) do
		local before, after = tonumber(old[key] or 0), assert(tonumber(new[key]))
		assert(before == 0 or after >= before * 0.7, key .. ' 较上一版本减少超过 30%，已拒绝更新并保留旧规则。')
		changes[key] = { previous = before, current = after, delta = after - before }
	end
	return changes
end

function M.firewall(devices)
	assert(#devices > 0, '没有可接管的 LAN 设备。')
	local names = {}
	for _, d in ipairs(devices) do
		assert(d:match('^[%w_.:%-]+$') and #d <= 15 and d ~= 'lo', '无效的网络设备。')
		names[#names + 1] = '"' .. d .. '"'
	end
	local text = ([=[table inet flowdns {
	chain guard {
		type filter hook input priority -10; policy accept;
		iifname "lo" return
		iifname != { %s } meta l4proto { tcp, udp } th dport { @DNS_PORT@, @TPROXY_PORT@ } counter drop
	}
	chain dns {
		type nat hook prerouting priority -110; policy accept;
		iifname { %s } meta l4proto { tcp, udp } th dport 53 counter redirect to :@DNS_PORT@
	}
	chain traffic {
		type filter hook prerouting priority -150; policy accept;
		iifname != { %s } return
		meta l4proto != { tcp, udp } return
		th dport 53 return
		ip daddr 198.18.0.0/15 meta l4proto { tcp, udp } meta mark set meta mark | 0x40000000 counter tproxy ip to :@TPROXY_PORT@ accept
		ip6 daddr fc00::/18 meta l4proto { tcp, udp } meta mark set meta mark | 0x40000000 counter tproxy ip6 to :@TPROXY_PORT@ accept
		fib daddr type local return
		ip daddr { 0.0.0.0/8, 10.0.0.0/8, 127.0.0.0/8, 169.254.0.0/16, 172.16.0.0/12, 192.168.0.0/16, 224.0.0.0/4, 240.0.0.0/4 } return
		ip6 daddr { ::/128, ::1/128, fc00::/7, fe80::/10, ff00::/8 } return
		meta l4proto { tcp, udp } meta mark set meta mark | 0x40000000 counter tproxy to :@TPROXY_PORT@ accept
	}
}
]=]):format(table.concat(names, ', '), table.concat(names, ', '), table.concat(names, ', '))
	text = text:gsub('@DNS_PORT@', tostring(M.dns_port)):gsub('@TPROXY_PORT@', tostring(M.tproxy_port))
	return text
end

return M
