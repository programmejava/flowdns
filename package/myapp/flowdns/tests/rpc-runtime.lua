-- Runtime test adapter. Uses the real nixio/jsonc libraries; confines file
-- operations to a temporary root and forbids real network/system mutations.
local script, root, method, scenario = arg[1], arg[2], arg[3], arg[4] or 'normal'
local extra = arg[5]
local fs = require 'nixio.fs'
local nixio = require 'nixio'
local json = require 'luci.jsonc'
local function q(s) return "'" .. s:gsub("'", "'\\''") .. "'" end
local function map(path)
	return (path:gsub('^/var/run/flowdns', root .. '/run'):gsub('^/etc/flowdns', root .. '/data'):gsub('^/etc/config', root .. '/router-config'))
end
local originals = {}
for _, name in ipairs({ 'mkdirr', 'mkdir', 'rmdir', 'stat', 'chmod', 'readfile', 'writefile', 'access', 'unlink' }) do
	originals[name] = fs[name]
	fs[name] = function(path, ...)
		if name == 'access' and path == '/etc/rc.d/S99flowdns' then
			local options = json.parse(originals.readfile(root .. '/options.json') or '{}') or {}
			return options.autostart == true
		end
		if scenario == 'ssr-bootstrap' and name == 'access' and path == '/sbin/fw4' then return true end
		if scenario == 'ssr-bootstrap' and name == 'access' and path == '/usr/share/shadowsocksr/gen_config.lua' then return true end
		if scenario == 'write-error' and name == 'writefile' then return nil, 28, 'No space left on device' end
		if scenario == 'chmod-error' and name == 'chmod' then return originals.chmod(map(path), 448) end
		if scenario == 'ssr-unconfigured' and name == 'readfile' then
			local port = dofile('package/myapp/flowdns/src/core.lua').dns_port
			if path == '/proc/net/tcp' then return (' 0: 00000000:%04X 00000000:0000 0A\n'):format(port) end
			if path == '/proc/net/udp' then return (' 0: 00000000:%04X 00000000:0000 07\n'):format(port) end
		end
		if scenario == 'ssr-bootstrap' and name == 'readfile' and path:match('^/proc/net/') then return '' end
		if scenario == 'supervised' and name == 'readfile' and path:match('^/proc/net/') then return '' end
		return originals[name](map(path), ...)
	end
end
local rename = fs.rename
fs.rename = function(source, target) return rename(map(source), map(target)) end
local native_open, file_open = nixio.open, io.open
nixio.open = function(path, ...) return native_open(map(path), ...) end
io.open = function(path, ...) return file_open(map(path), ...) end
package.preload['flowdns.transparent'] = function() return dofile('package/myapp/flowdns/src/transparent.lua') end
package.preload['flowdns.system'] = function() return dofile('package/myapp/flowdns/src/system.lua') end
if scenario == 'ssr-bootstrap' then
	local realpath, symlink, dir = fs.realpath, fs.symlink, fs.dir
	fs.realpath = function(path)
		local resolved = realpath(map(path))
		local prefix = root .. '/data'
		if resolved and resolved:sub(1, #prefix) == prefix then return '/etc/flowdns' .. resolved:sub(#prefix + 1) end
		return resolved
	end
	fs.symlink = function(source, target) return symlink(map(source), map(target)) end
	fs.dir = function(path) return dir(map(path)) end
end
-- Detect the exact API misuse with the real native library.
if scenario == 'mode-repro' then
	assert(fs.mkdirr('/var/run/flowdns'))
	assert(not pcall(fs.chmod, '/var/run/flowdns', 448))
	assert(fs.chmod('/var/run/flowdns', 700))
	assert(fs.stat('/var/run/flowdns').modestr == 'rwx------')
	print(json.stringify({ ok = true }))
	os.exit(0)
end
local is_rpc = script:match('/rpcd/luci%.flowdns$') ~= nil
local popen, execute = io.popen, os.execute
if is_rpc then
	io.popen = function(cmd)
		assert(cmd:match('^/usr/libexec/flowdns '), 'unexpected external command')
		if scenario == 'backend-error' then
			return { read = function() return 'lua: backend test failure\n' end, close = function() return true end }
		end
		local backend = 'package/myapp/flowdns/root/usr/libexec/flowdns'
		local runner = os.getenv('FLOWDNS_TEST_LUA')
		local prefix = q(runner) .. ' package/myapp/flowdns/tests/rpc-runtime.lua ' .. q(backend) .. ' ' .. q(root) .. ' '
		return popen((cmd:gsub('^/usr/libexec/flowdns ([%w]+)', function(name) return prefix .. name .. ' ' .. scenario end)))
	end
	os.execute = function(cmd)
		assert(cmd:match('^/usr/libexec/flowdns job '), 'unexpected system mutation')
		if scenario == 'spawn-error' then return 1 end
		local replacement = 'sh ' .. q(root .. '/worker.sh') .. ' job '
		cmd = cmd:gsub('^/usr/libexec/flowdns job ', function() return replacement end)
		cmd = cmd:gsub('/var/run/flowdns', function() return root .. '/run' end)
		return execute(cmd)
	end
	arg = { [0] = script, 'call', method }
else
	package.preload['flowdns.core'] = function() return dofile('package/myapp/flowdns/src/core.lua') end
	package.preload.uci = function()
		local ready = scenario == 'ssr-ready' or scenario == 'ssr-bootstrap'
		return { cursor = function() return {
			get_all = function(_, config)
				if config == 'flowdns' then
					local c = { enabled = scenario:match('^ssr%-') and '1' or '0', provider = scenario:match('^ssr%-') and 'ssrplus' or 'manual', direct_domains = { 'example.cn' } }
					for k, v in pairs(json.parse(fs.readfile(root .. '/options.json') or '{}') or {}) do c[k] = v end
					return c
				end
				if config == 'shadowsocksr' then
					local options = json.parse(fs.readfile(root .. '/options.json') or '{}') or {}
					return options.node or { type = 'v2ray' }
				end
			end,
			foreach = function(_, config, kind, callback)
				if config == 'shadowsocksr' and scenario ~= 'network-live' and scenario ~= 'native-network-live' then
					if kind == 'global' then callback({ global_server = ready and 'nil' or 'node1' }) end
					if kind == 'socks5_proxy' then callback({ enabled = ready and '1' or '0', server = ready and 'node1' or 'same', local_port = '1080', socks5_auth = 'noauth' }) end
				end
				if config == 'firewall' and kind == 'zone' and scenario == 'ssr-bootstrap' then callback({ network = { 'lan' }, input = 'ACCEPT' }) end
				return true
			end,
			get = function(_, config, section, option)
				if config == 'flowdns' and option == 'enabled' and scenario:match('^ssr%-') then return '1' end
			end
		} end }
	end
	io.popen = function(cmd)
		assert(not cmd:find('curl', 1, true), 'network access is forbidden in this test')
		local output = cmd:find('ubus call service', 1, true) and '{}' or 'Error: table does not exist\n'
		if scenario == 'supervised' and cmd:find('ubus call service', 1, true) then output = '{"flowdns":{"instances":{"main":{"running":true}}}}' end
		if cmd:find('FLOWDNS_EXIT', 1, true) then output = output .. '\nFLOWDNS_EXIT=1\n' end
		return { read = function() return output end, close = function() return true end }
	end
	os.execute = function(cmd)
		assert(cmd:match('^/usr/libexec/flowdns job '), 'unexpected system mutation: ' .. cmd)
		if scenario == 'spawn-error' then return 1 end
		local prefix = q(assert(os.getenv('FLOWDNS_TEST_LUA'))) .. ' package/myapp/flowdns/tests/rpc-runtime.lua ' .. q(script) .. ' ' .. q(root) .. ' job worker '
		return execute((cmd:gsub('^/usr/libexec/flowdns job ', function() return prefix end):gsub('/var/run/flowdns', function() return root .. '/run' end)))
	end
	if scenario == 'worker' then local sleep = nixio.nanosleep; nixio.nanosleep = function() return sleep(0, 500000000) end end
	if scenario == 'health-fixture' then
		local fixture = assert(json.parse(fs.readfile(root .. '/upstreams.json')))
		nixio.socket = function() return {
			setopt = function() return true end, connect = function() return fixture.proxy ~= false end,
			send = function() return true end, recv = function() return '\5\0' end, close = function() end
		} end
		io.popen = function(cmd)
			local output, code = '', 0
			if cmd:find('ubus call service', 1, true) then output = '{"flowdns":{"instances":{"main":{"running":true}}}}'
			elseif cmd:find('curl ', 1, true) then
				local provider
				for id, item in pairs(dofile('package/myapp/flowdns/src/core.lua').providers) do
					if cmd:find(item.ip, 1, true) then provider = id end
				end
				assert(provider, 'unknown provider fixture')
					if fixture.mutate_revision then assert(fs.writefile('/etc/config/shadowsocksr', 'replacement generation')) end
				if fixture[provider] == false then code, output = 1, 'fixture upstream failure'
				else
					local packet = assert(fs.readfile('/var/run/flowdns/probe.query'))
					assert(fs.writefile('/var/run/flowdns/probe.reply', packet:sub(1, 2) .. '\129\128\0\1\0\1\0\0\0\0' .. packet:sub(13)))
				end
			else error('unexpected health fixture command: ' .. cmd) end
			if cmd:find('FLOWDNS_EXIT', 1, true) then output = output .. '\nFLOWDNS_EXIT=' .. code .. '\n' end
			return { read = function() return output end, close = function() return true end }
		end
	end
	if scenario ~= 'health-fixture' and scenario ~= 'network-live' and scenario ~= 'native-network-live' then nixio.socket = function() error('network access is forbidden in backend test') end end
	if scenario == 'network-live' or scenario == 'native-network-live' then
		local parent = assert(os.getenv('FLOWDNS_TEST_PARENT_NETNS'), 'isolated namespace required')
		assert(fs.readlink('/proc/self/ns/net') ~= parent, 'refusing to use parent network namespace')
		local p = assert(popen('ip -j link show'))
		local links = assert(json.parse(p:read('*a'))); p:close()
		if scenario == 'native-network-live' then
			local expected = { lo = true, ['br-lan'] = true, target0 = true }
			assert(#links == 3, 'isolated three-interface fixture required')
			for _, link in ipairs(links) do assert(expected[link.ifname], 'unexpected fixture interface') end
		else
			assert(#links == 1 and links[1].ifname == 'lo', 'empty namespace required')
		end
		io.popen = function(cmd)
			if cmd:find('ubus call service', 1, true) then
				return { read = function() return '{"flowdns":{"instances":{"main":{"running":true}}}}' end, close = function() return true end }
			end
			assert(cmd:match('^nft ') or cmd:match('^ip %-') or cmd:match('^%( nft ') or cmd:match('^%( ip %-'), 'unexpected live command: ' .. cmd)
			return popen((cmd:gsub('/var/run/flowdns', function() return root .. '/run' end)))
		end
	end
	if scenario == 'ssr-bootstrap' then
		local restarted = false
		local ticks = 0
		nixio.nanosleep = function()
			if restarted then
				ticks = ticks + 1
				if ticks == 25 then assert(fs.writefile('/var/run/flowdns/attached', 'test')) end
			end
			return true
		end
		nixio.socket = function() return {
			setopt = function() return true end, connect = function() return true end, send = function() return true end,
			recv = function(_, size) return size == 2 and '\5\0' or '\5\0\0\1' end, close = function() return true end
		} end
		io.popen = function(cmd)
			local output = ''
			local options = json.parse(fs.readfile(root .. '/options.json') or '{}') or {}
			if options.missing_tool and cmd:find(options.missing_tool, 1, true) then
				return { read = function() return 'fixture: command unavailable\nFLOWDNS_EXIT=127\n' end, close = function() end }
			end
			if options.fail_check and cmd:find('sing-box check', 1, true) then
				return { read = function() return 'fixture: incompatible configuration\nFLOWDNS_EXIT=1\n' end, close = function() end }
			end
			if cmd:find('lua /usr/share/shadowsocksr/gen_config.lua', 1, true) then
				return popen(q(assert(os.getenv('FLOWDNS_TEST_LUA'))) .. ' package/myapp/flowdns/tests/ssr-generator.lua ' .. q(root) .. "; printf '\\nFLOWDNS_EXIT=%s\\n' \"$?\"")
			end
			if cmd:find('/usr/libexec/flowdns-dns --version', 1, true) then
				output = options.no_nftset and 'Dnsmasq fixture no-nftset\n' or 'Dnsmasq fixture nftset IPv6\n'
				return { read = function() return output .. '\nFLOWDNS_EXIT=0\n' end, close = function() end }
			end
			if cmd:find('/usr/libexec/flowdns-dns --test', 1, true) then
				return popen((cmd:gsub('/usr/libexec/flowdns%-dns', q(assert(os.getenv('FLOWDNS_TEST_FRONT'), 'private frontend fixture required'))):gsub('/var/run/flowdns', root .. '/run')))
			end
			if cmd:find('xray run -test', 1, true) then
				if options.fail_xray then return { read = function() return 'fixture Xray rejected\nFLOWDNS_EXIT=1\n' end, close = function() end } end
				local function remap(v)
					if type(v) == 'string' then return map(v) end
					if type(v) == 'table' then for k,x in pairs(v) do v[k] = remap(x) end end
					return v
				end
				assert(fs.writefile('/var/run/flowdns/checked-xray.json', json.stringify(remap(json.parse(fs.readfile('/var/run/flowdns/candidate-xray.json'))))))
				return popen((cmd:gsub('xray', q(assert(options.real_xray)), 1):gsub('candidate%-xray.json', 'checked-xray.json'):gsub('/var/run/flowdns', root .. '/run')))
			end
			if options.real_engine and (cmd:find('sing-box version', 1, true) or cmd:find('sing-box rule-set compile', 1, true) or cmd:find('sing-box check', 1, true)) then
				if cmd:find('sing-box check', 1, true) then
					local config = assert(cmd:match("%-c '([^']+)'"))
					local function map_config(value)
						if type(value) == 'string' then return (value:gsub('/etc/flowdns', root .. '/data')) end
						if type(value) == 'table' then for key, child in pairs(value) do value[key] = map_config(child) end end
						return value
					end
					assert(fs.writefile('/var/run/flowdns/engine-check.json', json.stringify(map_config(assert(json.parse(fs.readfile(config)))))))
					cmd = cmd:gsub(config, '/var/run/flowdns/engine-check.json', 1)
				end
				return popen((cmd:gsub('sing%-box', q(options.real_engine), 1):gsub('/etc/flowdns', root .. '/data'):gsub('/var/run/flowdns', root .. '/run')))
			end
			if cmd:find('sing-box version', 1, true) then output = options.version_output or 'sing-box version 1.12.25\n'
			elseif cmd:find('curl --version', 1, true) then output = 'curl fixture\n'
			elseif cmd:find('ip -Version', 1, true) then output = 'ip utility, iproute2-6.11.0\n'
			elseif cmd:find('nft --version', 1, true) then output = 'nftables fixture\n'
			elseif cmd:find('command -v timeout', 1, true) then output = '/usr/bin/timeout\n'
			elseif cmd:find('uname -m', 1, true) then output = 'fixture_arch\n'
			elseif cmd:find('sing-box rule-set compile', 1, true) then
				local dest = assert(cmd:match("%-%-output '([^']+)'")); assert(fs.writefile(dest, 'fixture-srs'))
			elseif cmd:find('curl ', 1, true) then
				if cmd:find('/dns-query', 1, true) then
					local packet = assert(fs.readfile('/var/run/flowdns/probe.query'))
					assert(fs.writefile('/var/run/flowdns/probe.reply', packet:sub(1, 2) .. '\129\128\0\1\0\1\0\0\0\0' .. packet:sub(13)))
					return {read=function() return '\nFLOWDNS_EXIT=0\n' end,close=function() return true end}
				end
				local name = assert(cmd:match('/([%w]+)%.download'), 'unknown fixture download')
				local lines = {}
				local options = json.parse(fs.readfile(root .. '/options.json') or '{}') or {}
				if options.fail_download then return { read = function() return 'fixture download failure\nFLOWDNS_EXIT=1\n' end, close = function() end } end
				for n = 1, name == 'ipv6' and 10 or (options.download_count or 100) do
					lines[#lines + 1] = name == 'domains' and ('server=/unit' .. n .. '.cn/223.5.5.5') or name == 'ipv4' and ('1.0.' .. n .. '.0/24') or ('2400:' .. n .. '::/32')
				end
				assert(fs.writefile('/var/run/flowdns/' .. name .. '.download', table.concat(lines, '\n')))
			elseif cmd:find('FLOWDNS_MODE=prepared /etc/init.d/flowdns start', 1, true) then
				restarted = true
			elseif cmd:find('/etc/init.d/flowdns stop', 1, true) then restarted = false
			elseif cmd:find('network.interface.lan', 1, true) then output = '{"up":true,"l3_device":"br-lan"}'
			elseif cmd:find('ubus call service', 1, true) then output = (restarted or options.supervised) and '{"flowdns":{"instances":{"main":{"running":true}}}}' or '{}'
			elseif cmd:find('nft -t list ruleset', 1, true) then output = options.firewall or ''
			elseif cmd:find('nft -t list table', 1, true) then
				output = restarted and '' or 'Error: missing table\n'
				if cmd:find('FLOWDNS_EXIT', 1, true) then output = output .. '\nFLOWDNS_EXIT=' .. (restarted and '0' or '1') .. '\n' end
				return { read = function() return output end, close = function() return true end }
			elseif not cmd:find('nft -t list ruleset', 1, true) and not cmd:find('sing%-box check') and not cmd:find('sing%-box rule%-set compile') and not cmd:find('nft %-c') then
				error('unexpected external command: ' .. cmd)
			end
			if cmd:find('FLOWDNS_EXIT', 1, true) then output = output .. '\nFLOWDNS_EXIT=0\n' end
			return { read = function() return output end, close = function() return true end }
		end
	end
	arg = { [0] = script, method, extra, arg[6] }
end
dofile(script)
