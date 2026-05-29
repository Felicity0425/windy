import json
import os
import polars as pl

STAGE1_DIR = "stage1_output"

def print_divider(title):
    print("\n" + "=" * 70)
    print(f"【 {title} 】")
    print("=" * 70)

def inspect_full_dataframe(file_name, label):
    path = os.path.join(STAGE1_DIR, file_name)
    if not os.path.exists(path):
        print(f"❌ 未找到文件: {path}")
        return None

    # 读取数据
    df = pl.read_parquet(path)
    print(f"统计 -> 数据源: {label} ({file_name}) | 总行数: {len(df)} | 总字段数: {len(df.columns)}")
    
    # 1. 打印完整的 Schema (字段名与数据类型)
    print("\n📋 完整字段结构与类型清单:")
    schema_kv = df.schema
    # 每行打印 3 个字段以节省空间
    schema_items = [f"{k}: {v}" for k, v in schema_kv.items()]
    for i in range(0, len(schema_items), 3):
        print("  |  ".join(schema_items[i:i+3]))

    # 2. 纵向全面抽样检查（避免横向太长显示不全）
    if len(df) > 0:
        print("\n🔍 随机抽取 1 条样本进行全字段细查 (检查乱码、空值与数值边界):")
        sample_dict = df.head(1).to_dicts()[0]
        for col, val in sample_dict.items():
            dtype_str = str(schema_kv[col])
            # 标记潜在的异常：如果是字符串且包含怪异编码，或者数值型全是 None
            alert = " ⚠️(Null)" if val is None else ""
            if isinstance(val, str) and ("\\x" in repr(val) or "" in val):
                alert = " 🚨(疑似乱码!!)"
            
            print(f"  ▪️ {col:<18} [{dtype_str:<8}] -> {repr(val)}{alert}")
    else:
        print("⚠️ 该文件数据行数为 0，无法抽样！")
        
    return df

def check_spatiotemporal_overlap(df_loc, df_wind):
    print_divider("时空边界交叉对齐验证")
    
    if df_loc is None or df_wind is None:
        print("❌ 由于缺少基础数据，无法进行时空边界对比。")
        return

    # 提取轨迹边界
    loc_t_min, loc_t_max = df_loc["time_utc"].min(), df_loc["time_utc"].max()
    loc_lon_min, loc_lon_max = df_loc["lon_clean"].min(), df_loc["lon_clean"].max()
    loc_lat_min, loc_lat_max = df_loc["lat_clean"].min(), df_loc["lat_clean"].max()

    # 区分风速数据源
    df_amdar = df_wind.filter(pl.col("source") == "amdar")
    df_turb = df_wind.filter(pl.col("source") == "turb")

    print("--- 时间维度对齐检查 (UTC) ---")
    print(f"1. 飞机轨迹 (Location) 时间范围 : {loc_t_min}  -->  {loc_t_max}")
    if len(df_amdar) > 0:
        print(f"2. 气象下传 (AMDAR)    时间范围 : {df_amdar['time_utc'].min()}  -->  {df_amdar['time_utc'].max()}")
    else:
        print("2. 气象下传 (AMDAR)    时间范围 : ❌ 无数据")
    if len(df_turb) > 0:
        print(f"3. 颠簸观测 (Turb)     时间范围 : {df_turb['time_utc'].min()}  -->  {df_turb['time_utc'].max()}")
    else:
        print("3. 颠簸观测 (Turb)     时间范围 : ❌ 无数据")

    print("\n--- 空间地理范围交叉检查 (经纬度) ---")
    print(f"飞机轨迹范围 : 经度 [{loc_lon_min:.3f}, {loc_lon_max:.3f}] | 纬度 [{loc_lat_min:.3f}, {loc_lat_max:.3f}]")
    if len(df_wind) > 0:
        print(f"风场气象范围 : 经度 [{df_wind['lon_clean'].min():.3f}, {df_wind['lon_clean'].max():.3f}] | 纬度 [{df_wind['lat_clean'].min():.3f}, {df_wind['lat_clean'].max():.3f}]")
    
    print("\n💡 验证结论提示：")
    print("  - 若时区未对齐：三种数据的【时间范围】会完全错开（例如相差 8 小时）。")
    print("  - 若坐标未对齐：风场和轨迹的【经纬度范围】会天差地别（例如一个在中国，一个在 0 度经线）。")

def main():
    # 1. 深度检查清洗后的轨迹文件
    print_divider("轨迹定位数据全字段体检 (clean_loc)")
    df_loc = inspect_full_dataframe("clean_loc.parquet", "飞机轨迹定位")

    # 2. 深度检查清洗后的风场气象文件（内部包含 AMDAR 和 颠簸）
    print_divider("气象风场数据全字段体检 (clean_wind)")
    df_wind = inspect_full_dataframe("clean_wind.parquet", "合并风场(AMDAR+TURB)")

    # 3. 进行交叉可视化验证
    check_spatiotemporal_overlap(df_loc, df_wind)

if __name__ == "__main__":
    main()