mount -t debugfs
sudo grep -R . /sys/kernel/debug/zswap

sysctl -a

grep -H . /sys/devices/system/cpu/vulnerabilities/*

cat /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor

cat /etc/docker/certs.d/10.118.96.1/ca.crt
cat /usr/local/share/ca-certificates/harbor-10.118.96.1.crt
