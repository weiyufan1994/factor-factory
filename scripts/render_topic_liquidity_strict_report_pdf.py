#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfbase.pdfmetrics import registerFont
from reportlab.platypus import (
    Image,
    KeepTogether,
    ListFlowable,
    ListItem,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
EVAL_DIR = REPO_ROOT / "evaluations/TOPIC_LIQUIDITY_DCMEMBER_20250102_20260423"
BT_DIR = EVAL_DIR / "self_quant_analyzer/tradable_open_backtest"
SUMMARY_CSV = BT_DIR / "tradable_open_backtest_summary.csv"
NAV_PNG = BT_DIR / "strict_tradable_hold_exit_variants_nav.png"
OUT_DIR = REPO_ROOT / "output/pdf"
OUT_PDF = OUT_DIR / "topic_liquidity_dragon_strict_tradable_report.pdf"
OUT_MD = EVAL_DIR / "topic_liquidity_dragon_strict_tradable_report.md"


def pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def fmt(value: float, digits: int = 3) -> str:
    return f"{value:.{digits}f}"


def load_key_rows() -> pd.DataFrame:
    df = pd.read_csv(SUMMARY_CSV)
    names = [
        "topic_top5_hot_gate",
        "topic_top5_hot_min3",
        "topic_top5_hot_min5",
        "topic_top5_hot_min3_trail10",
        "topic_top5_hot_min3_rsi45",
    ]
    return df[df["strategy"].isin(names)].copy()


def make_styles() -> dict[str, ParagraphStyle]:
    registerFont(UnicodeCIDFont("STSong-Light"))
    base = getSampleStyleSheet()
    styles = {
        "title": ParagraphStyle(
            "title",
            parent=base["Title"],
            fontName="STSong-Light",
            fontSize=22,
            leading=28,
            alignment=TA_CENTER,
            textColor=colors.HexColor("#172033"),
            spaceAfter=14,
        ),
        "subtitle": ParagraphStyle(
            "subtitle",
            parent=base["BodyText"],
            fontName="STSong-Light",
            fontSize=10,
            leading=15,
            alignment=TA_CENTER,
            textColor=colors.HexColor("#5d6678"),
            spaceAfter=18,
        ),
        "h1": ParagraphStyle(
            "h1",
            parent=base["Heading1"],
            fontName="STSong-Light",
            fontSize=15,
            leading=20,
            textColor=colors.HexColor("#19324d"),
            spaceBefore=12,
            spaceAfter=8,
        ),
        "body": ParagraphStyle(
            "body",
            parent=base["BodyText"],
            fontName="STSong-Light",
            fontSize=9.7,
            leading=15.2,
            textColor=colors.HexColor("#222222"),
            spaceAfter=7,
        ),
        "small": ParagraphStyle(
            "small",
            parent=base["BodyText"],
            fontName="STSong-Light",
            fontSize=8.5,
            leading=12,
            textColor=colors.HexColor("#505867"),
        ),
        "table": ParagraphStyle(
            "table",
            parent=base["BodyText"],
            fontName="STSong-Light",
            fontSize=8.2,
            leading=10.5,
            textColor=colors.HexColor("#222222"),
        ),
    }
    return styles


def p(text: str, styles: dict[str, ParagraphStyle], style: str = "body") -> Paragraph:
    return Paragraph(text, styles[style])


def bullet_list(items: list[str], styles: dict[str, ParagraphStyle]) -> ListFlowable:
    return ListFlowable(
        [ListItem(p(item, styles), leftIndent=8) for item in items],
        bulletType="bullet",
        leftIndent=14,
        bulletFontName="STSong-Light",
        bulletFontSize=8,
    )


def strategy_table(rows: pd.DataFrame, styles: dict[str, ParagraphStyle]) -> Table:
    labels = {
        "topic_top5_hot_gate": "1天换仓 top5 hot",
        "topic_top5_hot_min3": "至少持有3天",
        "topic_top5_hot_min5": "至少持有5天",
        "topic_top5_hot_min3_trail10": "3天 + 10% trailing stop",
        "topic_top5_hot_min3_rsi45": "3天 + RSI6<45退出",
    }
    table_data = [
        [
            p("版本", styles, "table"),
            p("NAV", styles, "table"),
            p("Sharpe", styles, "table"),
            p("最大回撤", styles, "table"),
            p("平均持仓", styles, "table"),
            p("买入受阻", styles, "table"),
            p("卖出受阻", styles, "table"),
        ]
    ]
    for _, row in rows.iterrows():
        table_data.append(
            [
                p(labels.get(row["strategy"], row["strategy"]), styles, "table"),
                p(fmt(row["final_nav"], 3), styles, "table"),
                p(fmt(row["sharpe_approx"], 2), styles, "table"),
                p(pct(row["max_drawdown"]), styles, "table"),
                p(f"{row['avg_completed_holding_trade_days']:.2f}天", styles, "table"),
                p(pct(row["buy_block_rate"]), styles, "table"),
                p(pct(row["sell_block_rate"]), styles, "table"),
            ]
        )
    table = Table(table_data, colWidths=[4.4 * cm, 1.6 * cm, 1.6 * cm, 2.0 * cm, 2.1 * cm, 1.9 * cm, 1.9 * cm])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e9eef6")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#172033")),
                ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#ccd3df")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    return table


def build_pdf() -> None:
    styles = make_styles()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rows = load_key_rows()
    doc = SimpleDocTemplate(
        str(OUT_PDF),
        pagesize=A4,
        rightMargin=1.35 * cm,
        leftMargin=1.35 * cm,
        topMargin=1.25 * cm,
        bottomMargin=1.25 * cm,
        title="题材资金龙头策略 - 严格可交易回测版",
    )
    story: list = []
    story.append(p("题材资金龙头策略", styles, "title"))
    story.append(p("严格无未来函数与可交易约束回测版", styles, "subtitle"))
    story.append(
        p(
            f"版本日期：{datetime.now().strftime('%Y-%m-%d')}；样本区间：2025-01-02 至 2026-04-23；"
            "数据源：Tushare 东方财富概念板块/成分、资金流、涨跌停与日行情。",
            styles,
            "small",
        )
    )
    story.append(Spacer(1, 8))

    story.append(p("1. 核心想法", styles, "h1"))
    story.append(
        p(
            "这个策略不是在寻找一个传统意义上每天都有稳定 IC 的截面因子，而是在寻找主题投资行情里最重要的现象："
            "新增资金是否正在少数题材里形成垄断式流入。当市场新增成交额上升，同时资金从其他板块释放并集中流入某些题材时，"
            "这些题材里的头部股票更容易成为短期龙头。",
            styles,
        )
    )
    story.append(
        bullet_list(
            [
                "外部新增资金：用全市场成交额的抬升刻画场外资金进入场内。",
                "板块轮动释放资金：资金流出的板块释放出可被其他题材争夺的流动资金。",
                "资金垄断程度：对正向流入题材计算 HHI，判断新增资金是否集中在少数方向。",
                "股票选择：在 hot topic gate 开启时，选择 topic_flow_hhi 排名靠前的题材龙头候选。",
            ],
            styles,
        )
    )

    story.append(p("2. 严格回测标准", styles, "h1"))
    story.append(
        p(
            "本版本按真实交易约束重新实现回测，目的不是追求更漂亮的曲线，而是排除未来函数与不可交易成交。"
            "信号只在事件日收盘后形成，最早只能在下一交易日开盘执行。",
            styles,
        )
    )
    story.append(
        bullet_list(
            [
                "无未来函数：event_trade_date 收盘后形成信号，只有当 trade_date 等于下一交易日时才保留样本。",
                "开盘成交：组合收益按 open-to-open 计算，不使用当日收盘后才知道的信息做当日交易。",
                "涨跌停限制：次日开盘涨停的股票视为买不进，资金留作现金；开盘跌停的持仓视为卖不出，继续冻结。",
                "交易成本：买入成本 7bps，卖出成本 12bps，包括佣金、卖出印花税和滑点。",
                "板块涨跌停幅度：主板 10%，科创/创业板 20%，北交所 30%，按股票代码前缀推断。",
            ],
            styles,
        )
    )

    story.append(p("3. 代码逻辑", styles, "h1"))
    story.append(
        p(
            "每日收盘后先计算每个东方财富概念板块的正资金流入、成交额、涨停数量、题材资金占比和资金 HHI。"
            "随后把题材信号映射到题材成分股，生成每只股票可获得的 topic_flow_hhi。"
            "策略先用 hot_topic_share 判断主题投资是否足够活跃，再在候选股票里按 topic_flow_hhi 排序选择 top 5%。"
            "持仓层面不再每日清空，而是至少持有 3 个交易日，以避免被题材发酵过程中的短期排名波动洗出去。"
            "满 3 日后，如果股票掉出候选、题材退潮或 RSI6 跌破 45，则进入退出流程；如果开盘跌停，则按真实约束继续持有。",
            styles,
        )
    )

    story.append(p("4. 严格回测结果", styles, "h1"))
    story.append(strategy_table(rows, styles))
    story.append(Spacer(1, 10))
    story.append(
        p(
            "结果显示，1天换仓版本在加入成本和交易约束后基本失效，说明这个策略不能用高频追换的方式交易。"
            "至少持有3天后，策略收益、夏普和回撤明显改善，说明题材龙头的收益来源更像是短期资金扩散和主线延续，"
            "而不是一天内的噪音。5天版本表现变差，说明过度持有容易吃到题材退潮。RSI6<45 的退出层进一步改善结果，"
            "但这个阈值仍需要后续做 walk-forward 和样本外稳健性检验。",
            styles,
        )
    )
    if NAV_PNG.exists():
        story.append(Image(str(NAV_PNG), width=17.0 * cm, height=9.3 * cm))
        story.append(p("图：严格可交易回测下的关键持仓/退出版本 NAV。", styles, "small"))

    story.append(PageBreak())
    story.append(p("5. 飞书推送与交易使用方式", styles, "h1"))
    story.append(
        p(
            "宏观一处的日报已经从“候选名单”升级为“交易日报”。推送会先给出 hot_topic_share gate 是否开启，"
            "再给出资金热流入题材 Top5 和明日龙头候选。如果 gate 关闭，日报只提供观察名单，不建议新增龙头仓。",
            styles,
        )
    )
    story.append(
        bullet_list(
            [
                "开仓：只在 hot_topic_share gate 开启时执行；次日开盘不涨停的候选才可以买入。",
                "仓位：候选股等权分散，避免只买一两只开盘涨停或波动过大的股票。",
                "持有：新买股票默认至少持有 3 个交易日，不因次日排名短期波动立刻卖出。",
                "退出：满 3 日后，若掉出候选、题材退潮或 RSI6<45，则按开盘卖出；若开盘跌停，则延后到可卖时执行。",
                "纪律：不在 gate 关闭时新增仓位；不追开盘涨停；不因为盘中情绪临时扩大仓位。",
            ],
            styles,
        )
    )

    story.append(p("6. 下一步", styles, "h1"))
    story.append(
        p(
            "下一版可以在不破坏严格回测标准的前提下加入“龙头识别增强层”：连续入榜次数、3日/5日动量、成交额放大、"
            "题材内资金排名，以及 TrendRadar 舆情 topic 是否与东方财富/同花顺/KPL 题材共振。"
            "这些增强项应作为 overlay 和推送解释层，而不是替代 topic_flow_hhi 的主触发信号。",
            styles,
        )
    )

    def footer(canvas, doc_obj):
        canvas.saveState()
        canvas.setFont("STSong-Light", 8)
        canvas.setFillColor(colors.HexColor("#6b7280"))
        canvas.drawString(1.35 * cm, 0.65 * cm, "Factor Factory - Topic Liquidity Dragon")
        canvas.drawRightString(A4[0] - 1.35 * cm, 0.65 * cm, f"Page {doc_obj.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)


def build_md() -> None:
    rows = load_key_rows()
    labels = {
        "topic_top5_hot_gate": "1天换仓 top5 hot",
        "topic_top5_hot_min3": "至少持有3天",
        "topic_top5_hot_min5": "至少持有5天",
        "topic_top5_hot_min3_trail10": "3天 + 10% trailing stop",
        "topic_top5_hot_min3_rsi45": "3天 + RSI6<45退出",
    }
    lines = [
        "# 题材资金龙头策略 - 严格可交易回测版",
        "",
        "信号日收盘后生成，次日开盘交易；开盘涨停买不进，开盘跌停卖不出；买入成本7bps，卖出成本12bps。",
        "",
        "| 版本 | NAV | Sharpe | 最大回撤 | 平均持仓 | 买入受阻 | 卖出受阻 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for _, row in rows.iterrows():
        lines.append(
            "| "
            + " | ".join(
                [
                    labels.get(row["strategy"], row["strategy"]),
                    fmt(row["final_nav"], 3),
                    fmt(row["sharpe_approx"], 2),
                    pct(row["max_drawdown"]),
                    f"{row['avg_completed_holding_trade_days']:.2f}天",
                    pct(row["buy_block_rate"]),
                    pct(row["sell_block_rate"]),
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "结论：1天换仓在严格成本后基本失效；至少持有3天明显改善；5天过长；3天+RSI6<45退出目前最好，但需要继续做样本外稳健性验证。",
        ]
    )
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    build_md()
    build_pdf()
    print(OUT_PDF)
    print(OUT_MD)


if __name__ == "__main__":
    main()
