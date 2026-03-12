
# run in temrinal: python3 midas/read_midas.py

import pandas as pd
import os
print(os.getcwd())

hazard_data = pd.read_csv('midas/midas_hazard_analysis_data.csv')
work_orders = pd.read_csv(
    "midas/CE_Work_Orders_200_20260210_180007(CE Work Orders).csv",
    encoding="cp1252"
)

print(hazard_data.head())
print(work_orders.head())
