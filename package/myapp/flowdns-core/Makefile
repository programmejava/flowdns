# SPDX-License-Identifier: GPL-3.0-or-later
include $(TOPDIR)/rules.mk

PKG_NAME:=flowdns-core
PKG_VERSION:=1.12.25
PKG_RELEASE:=1
PKG_SOURCE:=sing-box-$(PKG_VERSION).tar.gz
PKG_SOURCE_URL:=https://codeload.github.com/SagerNet/sing-box/tar.gz/v$(PKG_VERSION)?
PKG_HASH:=881435f07b5ab8170ccf3cb69e87130759521dc0ed1ae4bfeacbe7772a93a158
PKG_LICENSE:=GPL-3.0-or-later
PKG_LICENSE_FILES:=LICENSE
PKG_BUILD_DEPENDS:=golang/host
PKG_BUILD_PARALLEL:=1
PKG_BUILD_FLAGS:=no-mips16

GO_PKG:=github.com/sagernet/sing-box
GO_PKG_BUILD_PKG:=$(GO_PKG)/cmd/sing-box
GO_PKG_TAGS:=with_quic,with_utls
GO_PKG_LDFLAGS_X:=$(GO_PKG)/constant.Version=$(PKG_VERSION)

include $(INCLUDE_DIR)/package.mk
include $(TOPDIR)/feeds/packages/lang/golang/golang-package.mk

define Package/flowdns-core
  SECTION:=net
  CATEGORY:=Network
  TITLE:=Private sing-box engine for FlowDNS
  URL:=https://sing-box.sagernet.org/
  DEPENDS:=+ca-bundle
endef

define Package/flowdns-core/description
  Unmodified upstream sing-box installed only in FlowDNS's private PATH.
  Does not provide, replace, restart or reconfigure the system sing-box.
endef

define Build/Prepare
	mkdir -p $(PKG_BUILD_DIR)
	$(HOST_TAR) -xf $(DL_DIR)/$(PKG_SOURCE) -C $(PKG_BUILD_DIR) --strip-components=1
endef

define Package/flowdns-core/install
	$(INSTALL_DIR) $(1)/usr/libexec/flowdns-bin
	$(INSTALL_BIN) $(GO_PKG_BUILD_BIN_DIR)/sing-box $(1)/usr/libexec/flowdns-bin/sing-box
	$(INSTALL_DIR) $(1)/usr/share/flowdns-core
	$(INSTALL_DATA) $(PKG_BUILD_DIR)/LICENSE $(1)/usr/share/flowdns-core/LICENSE.sing-box
	$(INSTALL_DATA) ./COPYING $(1)/usr/share/flowdns-core/COPYING
endef

$(eval $(call BuildPackage,flowdns-core))
