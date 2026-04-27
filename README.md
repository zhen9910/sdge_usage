# sdge_usage

This script calculates SDGE eletricity usage at different time periods: Super-Off-Peak, Off-Peak and On-Peak.

It currently supports only SDGE Time-of-Use EV-TOU-5 price plan, additional plan usage will be added later. SDGE eletricity usage data can be downloaded from your SDGE account.

## EV-TOU-5 Time-of-Use Schedule

| Hours | Weekday | Weekend / Holiday |
|---|---|---|
| 12 AM – 6 AM | Super Off-Peak | Super Off-Peak |
| 6 AM – 10 AM | Off-Peak | Super Off-Peak |
| 10 AM – 2 PM | Super Off-Peak | Super Off-Peak |
| 2 PM – 4 PM | Off-Peak | Off-Peak |
| 4 PM – 9 PM | On-Peak | On-Peak |
| 9 PM – 12 AM | Off-Peak | Off-Peak |

> The 10 AM–2 PM Super Off-Peak window applies year-round on weekdays (updated per SDGE EV-TOU-5 rate change; previously this window was Super Off-Peak only in March and April).

python 3.10 or higher is required.

```
C:\project\sdge_usage> pip install openpyxl

C:\project\sdge_usage> pip install holidays

C:\project\sdge_usage> python ./sdge_usage.py ./data/Electric_15_Minute_3-14-2023_4-7-2023_20230407.xlsx

Electricity usage from 2023-03-14 00:00:00 to 2023-04-07 23:45:00

Super Off Peak net usage (kwh): 152.01000000000073 

Off Peak net usage (kwh):       -31.604999999999997

On Peak net usage (kwh):        -35.53499999999997

Total net usage (kwh):          84.87000000000077
```
