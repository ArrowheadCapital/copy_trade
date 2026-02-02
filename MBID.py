import wmi
import time

c = wmi.WMI()
for board in c.Win32_BaseBoard():
    print(board.SerialNumber.strip())
    break

time.sleep(5000)
