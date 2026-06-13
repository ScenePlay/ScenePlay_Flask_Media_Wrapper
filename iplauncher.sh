#!/bin/bash
#renice -n 19 -p $$
echo $1
echo $2
echo $3
start_dir=$(echo $1)
ipsearch=$(echo $2)
ip=$(echo $3)
cd $start_dir
python3 $ipsearch $ip
#echo $ipsearch $ip
#$ipsearch $ip

