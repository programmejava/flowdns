-- Run the actual repository SSR generator with a confined, non-secret UCI node.
local json = require 'luci.jsonc'
nixio = require 'nixio'
local root = assert(arg[1])
local options = json.parse(require('nixio.fs').readfile(root .. '/options.json') or '{}') or {}
local node = options.node or { type = 'v2ray', v2ray_protocol = 'vless', server = '127.0.0.1', server_port = '33445',
	vmess_id = '79bec4b7-45fb-4db7-8584-161d337dc2db', transport = 'raw', alias = 'fixture-native' }
luci = { sys = { exec = function(cmd)
	if cmd:find('type -t -p', 1, true) then return '/usr/bin/xray' end
	assert(cmd == 'xray version 2>&1', cmd); return 'Xray 25.2.21'
end } }
package.preload['luci.sys'] = function() return luci.sys end
package.preload['luci.model.uci'] = function() return { cursor = function() return {
	get_all = function(_, _, section)
		if section == 'node1' then return node end
		if section == '@global_xray_fragment[0]' then return { fragment = '0', noise = '0' } end
		if section == '@xray_noise_packets[0]' then return { enabled = '0' } end
		return {}
	end
} end } end
package.preload['luci.cbi.datatypes'] = function() return { hostname = function(s) return not s:match('^[%d.]+$') end } end
arg = { 'node1', 'tcp,udp', '15355', '0' }
if options.generator_variant then
	local output = print
	print = function(text)
		local generated = assert(json.parse(text))
		if options.generator_variant == 'no-tag' or options.generator_variant == 'direct-first-no-tag' then
			generated.outbounds[1].tag = nil
		elseif options.generator_variant == 'empty-tag' then generated.outbounds[1].tag = '' end
		if options.generator_variant == 'direct-first-no-tag' then
			table.insert(generated.outbounds, 1, table.remove(generated.outbounds, 2))
		end
		output(json.stringify(generated))
	end
end
dofile('feeds/helloworld/luci-app-ssr-plus/root/usr/share/shadowsocksr/gen_config.lua')
