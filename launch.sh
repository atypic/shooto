#/bin/bash
killall -9 python
python main.py -s localhost:1234 &
#python main.py -c localhost:1234 &
python main.py -c localhost:1234
