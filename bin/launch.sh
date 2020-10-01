#/bin/bash
killall -9 python
#This starts a server:
#python ../pewpew/main.py -s localhost:1234 &   
python ../pewpew/main.py -c localhost:1234
