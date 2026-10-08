import pandas as pd
import os

# 把这里替换成你真实的数据文件名
# 如果是在 data 文件夹里，路径就是 'data/你的文件名.parquet'
file_path = 'data/universal_enterprise_erp_fraud_dataset.parquet'

# 检查文件是否存在，防止路径写错
if not os.path.exists(file_path):
    print(f"❌ 找不到文件: {file_path}")
    print("请检查：1. 文件名对不对？ 2. 是不是放在 data 文件夹里了？ 3. 后缀是 .csv 还是 .parquet？")
else:
    # 读取数据
    df = pd.read_parquet(file_path)  # 如果是 parquet 文件，请改成 pd.read_parquet(file_path)

    print("✅ 数据读取成功！")
    print("-" * 30)

    # 1. 看看前5行数据长什么样
    print("【前5行数据预览】:")
    print(df.head())
    print("-" * 30)

    # 2. 看看有多少行、多少列，以及每列的数据类型
    print("【数据总体信息】:")
    df.info()
    print("-" * 30)

    # 3. 看看数值列的统计摘要（最大值、最小值、平均值等）
    print("【数值列统计摘要】:")
    print(df.describe())