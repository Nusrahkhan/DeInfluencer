import pandas as pd

df = pd.read_csv("klairs_vitamin_c_serum_reddit.csv")

# Option B1: Unix epoch seconds (bigint-friendly)
df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y%m%d").astype(int)

df.to_csv("klairs_vitamin_c_serum_reddit_fixed.csv", index=False)