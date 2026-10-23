-- Run with the buildroot's host Lua 5.1. No target libraries are required.
local out = assert(arg[1], 'output directory required')
package.path = 'package/myapp/flowdns/src/?.lua;' .. package.path
local core = require 'core'
local count = 0
local function test(name, fn)
	local ok, err = pcall(fn)
	assert(ok, name .. ': ' .. tostring(err))
	count = count + 1
end
local function rejects(fn) assert(not pcall(fn), 'expected rejection') end
local function copy(v)
	if type(v) ~= 'table' then return v end
	local t = {}; for k, x in pairs(v) do t[k] = copy(x) end; return t
end
local function encode(v)
	if type(v) == 'string' then
		return '"' .. v:gsub('[%z\1-\31\\"]', function(c) return ('\\u%04x'):format(c:byte()) end) .. '"'
	elseif type(v) == 'boolean' or type(v) == 'number' then return tostring(v)
	elseif type(v) == 'table' then
		local entries = {}
		if #v > 0 then
			for _, x in ipairs(v) do entries[#entries + 1] = encode(x) end
			return '[' .. table.concat(entries, ',') .. ']'
		end
		for k, x in pairs(v) do entries[#entries + 1] = encode(k) .. ':' .. encode(x) end
		table.sort(entries)
		return '{' .. table.concat(entries, ',') .. '}'
	end
	error('unsupported value')
end
if arg[2] == '--jsonc' then
	local json = require 'luci.jsonc'
	encode = function(value)
		local text = assert(json.stringify(value))
		local function equal(expected, actual)
			assert(type(expected) == type(actual), 'JSON changed a rule condition type')
			if type(expected) == 'table' then
				for key, item in pairs(expected) do equal(item, actual[key]) end
			else assert(expected == actual, 'JSON changed a rule condition') end
		end
		equal(value, json.parse(text))
		assert(not text:find(':null', 1, true), 'a rule condition was serialized as null')
		return text
	end
end
local function write(path, v)
	local f = assert(io.open(path, 'w')); f:write(type(v) == 'table' and encode(v) or v); f:close()
end
local base = {
	provider = 'manual', proxy_port = 1080, domestic_dns = 'alidns', overseas_dns = 'cloudflare',
	transport = 'https', udp = true, log_level = 'info', local_dns_port = 53,
	local_domains = { 'lan', 'local', 'home.arpa' }, direct_domains = { 'custom.cn' },
	proxy_domains = { 'force-proxy.cn' }, realip_domains = { 'compat.example' }
}
local rules = { domains = { 'qq.com', 'force-proxy.cn' } }
test('DNS cooldown and unhealthy backup never trigger switching', function()
	local now = 10000
	local r = core.dns_health({ failures = 3, switched = now - 20 }, 'google', 'google', false, false, true, now, true)
	assert(r.active == 'google')
	r = core.dns_health({ failures = 3 }, 'google', 'google', false, false, false, now, true)
	assert(r.active == 'google')
end)
test('rule update checks all three datasets and reports differences', function()
	local before = { domain_count = 1000, ipv4_count = 1000, ipv6_count = 100 }
	local after = { domain_count = 1100, ipv4_count = 1000, ipv6_count = 90 }
	assert(core.rule_change(before, after).domain_count.delta == 100)
	after.ipv4_count = 699; rejects(function() core.rule_change(before, after) end)
end)
test('health and schedule values have bounded ranges', function()
	local c = copy(base); c.health_interval = 1; rejects(function() core.validate(c) end)
	c = copy(base); c.update_days = 100; rejects(function() core.validate(c) end)
end)
test('binary rules and active backup retain the original DNS path', function()
	local c = core.validate(copy(base)); c.binary_rules = true; c.overseas_active = 'google'
	local cfg = core.config(c, out)
	assert(cfg.route.rule_set[1].format == 'binary' and cfg.route.rule_set[1].path == out .. '/domains.srs')
	assert(cfg.dns.servers[2].server == core.providers.google.ip and cfg.dns.servers[2].detour == 'proxy')
end)
test('numeric JSON rule ownership', function()
	assert(core.owns_rule({ priority = 20260, src = 'all', fwmark = '0x40000000', fwmask = '0x40000000', table = '20260' }))
	assert(core.owns_rule({ priority = 20260, fwmark = 1073741824, fwmask = 1073741824, table = 20260 }))
end)
test('foreign rule selectors are never considered ours', function()
	local r = { priority = 20260, src = 'all', fwmark = '0x40000000', fwmask = '0x40000000', table = '20260' }
	r.iif = 'br-guest'; assert(not core.owns_rule(r))
	r.iif = nil; r.src = '192.168.1.0/24'; assert(not core.owns_rule(r))
	r.src = 'all'; r.fwmask = '0xffffffff'; assert(not core.owns_rule(r))
	r.fwmask = '0x40000000'; r.flags = { 'not' }; assert(not core.owns_rule(r))
end)
test('numeric and named local route types and default prefixes', function()
	for _, destination in ipairs({ 'default', '0.0.0.0/0', '::/0' }) do
		assert(core.owns_route({ table = '20260', type = '2', dst = destination, dev = 'lo' }))
		assert(core.owns_route({ table = 20260, type = 'local', dst = destination, dev = 'lo' }))
	end
end)
test('foreign route destinations and gateways are never considered ours', function()
	assert(not core.owns_route({ table = 20260, type = 'blackhole', dst = 'default', dev = 'lo' }))
	assert(not core.owns_route({ table = 20260, type = 'local', dst = '192.0.2.0/24', dev = 'lo' }))
	assert(not core.owns_route({ table = 20260, type = 'local', dst = 'default', dev = 'lo', gateway = '192.0.2.1' }))
end)
test('normalization', function() assert(core.domain('  WWW.Example.COM. ') == 'www.example.com') end)
test('suffix boundary', function() assert(core.matches('a.qq.com', 'qq.com')); assert(not core.matches('notqq.com', 'qq.com')) end)
for _, value in ipairs({ 'https://qq.com', 'qq.com:443', 'a..com', '-a.com', 'a-.com', '1.2.3.4', 'a.com;touch /tmp/x', '*.com', string.rep('a', 64) .. '.com' }) do
	test('invalid domain ' .. value, function() assert(not core.domain(value)) end)
end
test('deduplication', function() assert(#core.domains({ 'QQ.com', 'qq.com' }) == 1) end)
test('manual proxy precedes domestic data', function()
	local c = core.validate(copy(base)); assert(core.classify(c, rules, 'www.force-proxy.cn').action == 'proxy')
end)
test('domestic real IP', function()
	local r = core.classify(core.validate(copy(base)), rules, 'www.qq.com'); assert(r.action == 'direct' and not r.fakeip)
end)
test('unknown domain proxy default', function()
	local r = core.classify(core.validate(copy(base)), rules, 'unknown.example'); assert(r.action == 'proxy' and r.fakeip)
end)
test('compatibility retains route', function()
	local r = core.classify(core.validate(copy(base)), rules, 'compat.example'); assert(r.action == 'proxy' and not r.fakeip)
end)
test('local names never leave LAN resolver', function()
	assert(core.classify(core.validate(copy(base)), rules, 'nas.lan').action == 'local')
end)
test('private PTR stays local, public PTR uses encrypted upstream', function()
	local c = core.validate(copy(base))
	assert(core.classify(c, rules, '1.1.168.192.in-addr.arpa').action == 'local')
	assert(core.classify(c, rules, '8.8.8.8.in-addr.arpa').action == 'proxy')
end)
test('overlapping manual rules rejected', function()
	local c = copy(base); c.proxy_domains = { 'a.custom.cn' }; rejects(function() core.validate(c) end)
end)
test('internal ports cannot become upstream', function()
	local c = copy(base); c.proxy_port = core.dns_port; rejects(function() core.validate(c) end)
end)
test('plaintext transport forbidden', function()
	local c = copy(base); c.transport = 'udp'; rejects(function() core.validate(c) end)
end)
test('IPv4 parsing and limits', function()
	assert(core.cidr('1.2.3.0/24', 4)); assert(not core.cidr('256.2.0.0/16', 4)); assert(not core.cidr('0.0.0.0/0', 4)); assert(not core.cidr('1.2.3/24', 4))
end)
test('IPv6 parsing and limits', function()
	assert(core.cidr('2400:3200::/32', 6)); assert(not core.cidr('2400:::1/32', 6)); assert(not core.cidr('::/0', 6)); assert(not core.cidr('1:2:3:4:5:6:7:8:9/32', 6))
end)
test('download cannot be HTML', function()
	assert(#core.parse_china('<html>error</html>') == 0); rejects(function() core.parse_cidrs('<html>error</html>', 4) end)
end)
test('dnsmasq source extraction', function()
	local d = core.parse_china('# comment\nserver=/qq.com/114.114.114.114\nserver=/QQ.com/1.2.3.4\n'); assert(#d == 1 and d[1] == 'qq.com')
end)
test('interface injection rejected', function() rejects(function() core.firewall({ 'br-lan"; flush ruleset' }) end) end)
test('Fake-IP IPv6 before private bypass', function()
	local text = core.firewall({ 'br-lan' }); assert(text:find('ip6 daddr fc00::/18', 1, true) < text:find('fc00::/7', 1, true))
	assert(text:find('priority %-110')); assert(text:find('th dport 53 return', 1, true))
	assert(text:find('redirect to :' .. core.dns_port, 1, true)); assert(not text:find('@DNS_PORT@', 1, true))
end)

write(out .. '/domains.json', { version = 3, rules = { { domain_suffix = rules.domains } } })
write(out .. '/ip.json', { version = 3, rules = { { ip_cidr = { '114.114.114.0/24', '2400:3200::/32' } } } })
local index = 0
for _, transport in ipairs({ 'https', 'tls' }) do
	for _, domestic in ipairs({ 'alidns', 'dnspod' }) do
		for _, overseas in ipairs({ 'google', 'cloudflare' }) do
			for _, udp in ipairs({ true, false }) do
				local c = copy(base); c.transport, c.domestic_dns, c.overseas_dns, c.udp = transport, domestic, overseas, udp
				c.binary_rules = arg[3] == '--binary'
				local cfg = core.config(core.validate(c), out)
				cfg.log.output, cfg.experimental.cache_file.path = out .. '/core.log', out .. '/cache.db'
				test('encrypted upstream invariants ' .. index, function()
					assert(cfg.dns.servers[1].detour == 'direct' and cfg.dns.servers[2].detour == 'proxy')
					assert(cfg.dns.servers[1].tls.server_name and not cfg.dns.servers[1].tls.insecure)
					if not udp then assert(cfg.outbounds[2].network == 'tcp') end
				end)
				index = index + 1
				write(out .. '/config-' .. index .. '.json', cfg)
			end
		end
	end
end
write(out .. '/firewall.nft', core.firewall({ 'br-lan', 'br-guest' }))
print(('PASS: %d policy checks; %d sing-box configurations generated'):format(count, index))
