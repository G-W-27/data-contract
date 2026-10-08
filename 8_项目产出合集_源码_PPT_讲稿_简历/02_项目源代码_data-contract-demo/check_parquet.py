import pandas as pd


df = pd.read_parquet(
    "financial_data.parquet"
)


print(df.head())

print("================")

print(df.dtypes)

print("================")

print(df.shape)