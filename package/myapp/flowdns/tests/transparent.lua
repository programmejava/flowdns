local root = assert(arg[1])
package.path = 'package/myapp/flowdns/src/?.lua;' .. package.path
local core, native, json = require 'core', require 'transparent', require 'luci.jsonc'
local function write(name, data)
	local f = assert(io.open(root .. '/' .. name, 'w')); f:write(type(data) == 'table' and json.stringify(data) or data); f:close()
end
local c = core.validate({ mode = 'transparent', provider = 'ssrplus', proxy_port = 1080, domestic_dns = 'alidns', overseas_dns = 'google',
	transport = 'https', udp = true, log_level = 'warn', local_dns_port = 53, local_domains = { 'lan', 'local', 'home.arpa' },
	direct_domains = { 'manual-direct.example' }, proxy_domains = { 'manual-proxy.cn' }, realip_domains = {}, devices = { 'br-lan' }, binary_rules = true })
local dns = core.config(c, root)
assert(#dns.inbounds == 1 and dns.inbounds[1].listen_port == core.dns_backend_port)
assert(#dns.dns.servers == 3 and dns.dns.servers[2].detour == 'proxy' and dns.dns.final == 'overseas')
for _, rule in ipairs(dns.dns.rules) do assert(rule.server ~= 'fakeip') end
assert(not core.classify(c, { domains = { 'qq.com' } }, 'outside.example').fakeip)
local config = native.xray(c, { dns = { servers = { '8.8.8.8' } }, routing = { rules = { 'must-not-inherit' } }, outbounds = {
	{ tag = 'node', protocol = 'vless', settings = { vnext = { { address = '127.0.0.1', port = 33445,
		users = { { id = '79bec4b7-45fb-4db7-8584-161d337dc2db', encryption = 'none' } } } } } } } })
assert(not config.dns and config.routing.rules[1].outboundTag == 'node')
assert(config.inbounds[1].streamSettings.sockopt.tproxy == 'tproxy' and not config.inbounds[1].sniffing.enabled)
local old_generator = { outbounds = { { tag = 'flowdns-node', protocol = 'freedom' },
	{ protocol = 'vless', settings = config.outbounds[1].settings, streamSettings = { network = 'raw' } } } }
local compatible = native.xray(c, old_generator)
assert(compatible.routing.rules[1].outboundTag == 'flowdns-node-1')
assert(compatible.outbounds[1].protocol == 'freedom' and compatible.outbounds[2].tag == 'flowdns-node-1')
assert(old_generator.outbounds[2].tag == nil, 'adapter must not mutate generated configuration')
local selected = {}; for k,v in pairs(c) do selected[k] = v end; selected.ssr_node = 'node1'
local multi = { outbounds = { { tag = 'other', protocol = 'vmess' }, { tag = 'node1:fixture', protocol = 'vless' } } }
assert(native.xray(selected, multi).routing.rules[1].outboundTag == 'node1:fixture')
assert(not pcall(native.xray, c, multi), 'ambiguous proxy selection must fail before apply')
local vision = {outbounds={{protocol='vless',settings={vnext={{users={{flow='xtls-rprx-vision'}}}}}}}}
local auto={}; for k,v in pairs(c) do auto[k]=v end
native.xray(auto,vision); assert(auto.quic_effective=='reject')
local allow={}; for k,v in pairs(c) do allow[k]=v end; allow.quic_policy='allow'
local allowed=native.xray(allow,vision)
assert(allowed.outbounds[1].settings.vnext[1].users[1].flow=='xtls-rprx-vision-udp443')
assert(vision.outbounds[1].settings.vnext[1].users[1].flow=='xtls-rprx-vision')
local changed={}; for k,v in pairs(c) do changed[k]=v end; changed.overseas_dns='cloudflare'
assert(native.dns_only(c,changed))
changed.proxy_port=1081; assert(not native.dns_only(c,changed)); changed.proxy_port=c.proxy_port
changed.rules_version='other'; assert(not native.dns_only(c,changed))
local rejected={};for k,v in pairs(c)do rejected[k]=v end;rejected.quic_policy='reject';rejected.quic_effective='reject'
write('native-reject-firewall.nft',native.firewall(rejected,{'203.0.113.0/24','2001:db8:44::/48'},core))
write('native-policy.json', c)
write('native-dns.json', dns)
-- Exercise a real direct-first/tagless generator variant in the LAN test.
write('native-xray.json', compatible)
write('native-dnsmasq.conf', native.dnsmasq(c, { 'qq.com' }))
write('native-firewall.nft', native.firewall(c, { '203.0.113.0/24', '2001:db8:44::/48' }, core))
local bad = {}; for k,v in pairs(c) do bad[k] = v end
bad.provider = 'passwall'; assert(not pcall(core.validate, bad))
assert(not pcall(native.firewall, c, { '1.2.3.4; flush ruleset' }, core))
assert(not pcall(native.xray, c, { outbounds = { { tag = 'direct', protocol = 'freedom' } } }))
print('PASS: transparent DNS, native Xray-only data plane, real-IP policy and invalid input checks')
print('PASS: missing/empty tags and reordered outbounds are adapted without mutating input or guessing among multiple nodes')
