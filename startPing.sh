#!/bin/bash
renice -n 19 -p $$
base=$(echo $1)
python3 pinger.py $base$i;
