#!/bin/bash

username=$1
password="password"
[ "$2" != "" ] && password=$2

useradd -m -d /home/$username -s /bin/bash $username
echo -ne "$password\n$password\n" | passwd $username
echo -ne "$password\n$password\n" | smbpasswd -a $username
gpasswd -a $username docker
