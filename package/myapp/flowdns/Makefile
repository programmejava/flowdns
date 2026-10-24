include $(TOPDIR)/rules.mk

PKG_NAME:=flowdns
PKG_VERSION:=1.0.2
PKG_RELEASE:=1
PKG_LICENSE:=GPL-3.0-or-later GPL-2.0
PKG_LICENSE_FILES:=COPYING
PKG_SOURCE:=dnsmasq-2.93.tar.xz
PKG_SOURCE_URL:=https://thekelleys.org.uk/dnsmasq/
PKG_HASH:=0c00d4e5c97c8306e5fb932b348b34269c9c29a0e7df0e8e82958b407092bc19
PKG_BUILD_PARALLEL:=1

include $(INCLUDE_DIR)/package.mk

define Package/flowdns
  SECTION:=net
  CATEGORY:=Network
  TITLE:=Unified DNS and transparent routing policy
  DEPENDS:=+sing-box +lua +libuci-lua +luci-lib-jsonc +luci-lib-nixio +curl +ca-bundle +coreutils-timeout +ip-full +nftables-json +kmod-nft-tproxy
endef

define Package/flowdns/conffiles
/etc/config/flowdns
/etc/flowdns/
endef

define Build/Prepare
	mkdir -p $(PKG_BUILD_DIR)
	$(HOST_TAR) -xf $(DL_DIR)/$(PKG_SOURCE) -C $(PKG_BUILD_DIR) --strip-components=1
endef

define Build/Configure
endef

define Build/Compile
	$(MAKE) -C $(PKG_BUILD_DIR) $(TARGET_CONFIGURE_OPTS) \
		CFLAGS="$(TARGET_CFLAGS) $(TARGET_CPPFLAGS)" LDFLAGS="$(TARGET_LDFLAGS)" \
		COPTS="-DHAVE_NFTSET -DNO_DHCP -DNO_DHCP6 -DNO_TFTP -DNO_SCRIPT -DNO_AUTH -DNO_IPSET -DNO_INOTIFY" \
		PREFIX=/usr
endef

define Package/flowdns/install
	$(CP) ./root/* $(1)/
	$(INSTALL_BIN) $(PKG_BUILD_DIR)/src/dnsmasq $(1)/usr/libexec/flowdns-dns
	$(INSTALL_DIR) $(1)/usr/share/flowdns
	$(INSTALL_DATA) $(PKG_BUILD_DIR)/COPYING $(1)/usr/share/flowdns/COPYING.dnsmasq
	$(INSTALL_DATA) ./COPYING $(1)/usr/share/flowdns/COPYING.flowdns
	$(INSTALL_DIR) $(1)/etc/flowdns/rules
	$(INSTALL_DIR) $(1)/usr/lib/lua/flowdns
	$(INSTALL_DATA) ./src/*.lua $(1)/usr/lib/lua/flowdns/
endef

$(eval $(call BuildPackage,flowdns))
