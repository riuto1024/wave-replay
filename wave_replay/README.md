# WAVE-Replay V0.2

一个零付费起步的 WAVE 推演引擎行为复现原型。

## 当前目标

V0.1 不追求页面 1:1，而是先复现最影响推演结果的核心链路：

1. 免费 OHLCV 行情读取
2. WAVE 风格固定基础特征
   - 20周期量比
   - 5周期动量
   - 20周期动量
   - 日内收盘位置
   - 30 / 365 周期高低点
3. 多尺度结构节点（Swing High / Low）
4. Fibonacci 0.382 / 0.5 / 0.618 / 0.786
5. Fibonacci 扩展 0.618 / 1.0 / 1.618 / 2.0
6. 结构点 + Fib + 成交密集区 + 心理整数位 共振聚类
7. Elliott Wave 确定性候选计数
8. 结构失效位候选
9. BTC / ETH 已知 WAVE 样本节点对照
10. TXT / JSON / CSV 导出

## 为什么先不接AI

已经观察到 WAVE 报告中存在少量日期/斐波那契文案前后不一致。
因此第一阶段先把确定性计算层跑稳，再加入 LLM 文本层，避免“看起来像，但核心节点不一样”。

## 本地运行（Windows）

### 最简单

双击：

`run_local.bat`

第一次会自动安装依赖。

### 手动

```bat
py -m pip install -r requirements.txt
py -m streamlit run streamlit_app.py
```

浏览器会自动打开。

## 免费部署到 WEB

推荐 Streamlit Community Cloud：

1. 注册/登录 GitHub。
2. 新建一个仓库，例如 `wave-replay`。
3. 把本项目所有文件上传到仓库根目录。
4. 打开 Streamlit Community Cloud。
5. 选择 `Create app` / `Deploy an app`。
6. 选择刚才的 GitHub 仓库。
7. Main file path 填：
   `streamlit_app.py`
8. Python 建议选 3.12。
9. 点击 Deploy。
10. 几分钟后会得到：
   `https://你的名字.streamlit.app`

这个版本不需要购买服务器，不需要数据库，也不需要 Binance API Key。

## Binance 免费行情

程序优先使用 Binance 公共 market-data-only 端点：

`https://data-api.binance.vision/api/v3/klines`

失败时自动回退到其它 Binance 公共 REST 端点。

## CSV 格式

要支持 A股、黄金或其它自有行情时，上传 CSV：

```csv
date,open,high,low,close,volume
2026-08-01,100,105,98,103,123456
...
```

也兼容以下时间字段名：

- date
- datetime
- time
- timestamp
- 日期
- 时间

## 重要说明

WAVE-Replay V0.2 是黑盒行为复现研究原型。
它没有、也不声称拥有 WAVE 的私有源码、私有模型或后台算法。

V0.1 的评价标准是：

- 结构节点命中率
- 结构节点价格误差
- 关键区域误差
- 失效位误差
- Elliott 候选结构一致率

后续版本再逐项校准。


## V0.2 相比 V0.1 的关键修正

1. 增加“WAVE样本复现模式”。
   - BTC/ETH 自动使用内置 WAVE 报告时间。
   - 抓取报告时刻以前的 1H K线，再重建当时可见的日K。
   - 避免历史回测时误用当天结束后的完整日K。

2. 基准评分不再“全局找价格最近点”。
   - 结构节点按 H/L 类型 + 日期窗口匹配。
   - 同一个 Replay 节点不能被重复匹配给多个 WAVE 节点。
   - 时间窗内没有命中就明确显示“未命中”。

3. 支撑/阻力区域单独评分。
   - WAVE 的 1828.81-1848.63 这类“区域”不再拿单个 Swing 点硬配。
   - 改成与 Replay 共振区间比较。

4. 增加基准价偏差检查。
   - 当前/重建基准价与 WAVE 样本偏差超过 1% 时给出警告。
   - 避免把不同日期的数据误差当成算法误差。

因此 V0.1 截图里的 4.11% 不能直接当作真实复现误差，V0.2 的评分口径更严格。
