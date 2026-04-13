#!/bin/bash
#
# newuser.sh <username> <password> [uid] [gid]
# create a new user with username, passwrd, uid and gid.
# uid and gid is optional

username=$1
password="password"
[ "$2" != "" ] && password=$2
uid=$3
gid=$4

create_home="-m"
[ -d /home/$username ] && create_home="-M"

gid_opt=""
if [ "$gid" != "" ]; then
    groupadd -g $gid $username
    gid_opt="-g $gid"
fi

uid_opt=""
[ "$uid" != "" ] && uid_opt="-u $uid"

useradd $create_home $uid_opt $gid_opt -d /home/$username -s /bin/bash $username
echo -ne "$password\n$password\n" | passwd $username
echo -ne "$password\n$password\n" | smbpasswd -a $username
gpasswd -a $username docker

