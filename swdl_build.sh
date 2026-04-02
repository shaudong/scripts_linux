#!/bin/sh

if [ "`grep CONFIG_FEED_feed_prpl openwrt/.config`" != "" ]; then
	sed -i '/CONFIG_VERSION_NUMBER=/s/=.*$/="1.1.10"/' openwrt/.config
	./perform.sh app
	sed -i '/CONFIG_VERSION_NUMBER=/s/=.*$/="1.1.20"/' openwrt/.config
	./perform.sh app
	sed -i '/CONFIG_VERSION_NUMBER=/s/=.*$/="1.1.30"/' openwrt/.config
	./perform.sh app
else
	echo CONFIG_VERSION_ARCWRT_PROJECT_NUMBER="1.1.10" >> openwrt/.config
	./perform.sh app
	sed -i '/CONFIG_VERSION_ARCWRT_PROJECT_NUMBER=/s/=.*$/="1.1.20"/' openwrt/.config
	./perform.sh app
	sed -i '/CONFIG_VERSION_ARCWRT_PROJECT_NUMBER=/s/=.*$/="1.1.30"/' openwrt/.config
	./perform.sh app
fi

