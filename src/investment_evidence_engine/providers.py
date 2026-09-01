from __future__ import annotations

from datetime import date

import pandas as pd


class ProviderError(RuntimeError):
    pass


def normalize_ohlcv(frame: pd.DataFrame) -> pd.DataFrame:
    required = {"date", "open", "high", "low", "close", "volume"}
    missing = required - set(frame.columns)
    if missing:
        raise ProviderError(f"missing OHLCV columns: {sorted(missing)}")
    out = frame.copy()
    out["date"] = pd.to_datetime(out["date"], errors="raise").dt.normalize()
    for column in ("open", "high", "low", "close", "volume"):
        out[column] = pd.to_numeric(out[column], errors="coerce")
    for optional in ("amount", "turnover"):
        if optional in out.columns:
            out[optional] = pd.to_numeric(out[optional], errors="coerce")
    out = out.sort_values("date").drop_duplicates("date", keep="last").reset_index(drop=True)
    if out.empty:
        raise ProviderError("provider returned no rows")
    if out[["open", "high", "low", "close"]].isna().any().any():
        raise ProviderError("provider returned non-numeric required price fields")
    if (out[["open", "high", "low", "close"]] <= 0).any().any():
        raise ProviderError("provider returned non-positive price")
    return out


class AKShareProvider:
    name = "akshare"

    def get_daily_bars(
        self,
        symbol: str,
        start: date,
        end: date,
        adjust: str = "qfq",
    ) -> pd.DataFrame:
        try:
            import akshare as ak
        except ImportError as exc:
            raise ProviderError("akshare is not installed") from exc
        raw = ak.stock_zh_a_hist(
            symbol=symbol,
            period="daily",
            start_date=start.strftime("%Y%m%d"),
            end_date=end.strftime("%Y%m%d"),
            adjust=adjust,
        )
        if raw is None or raw.empty:
            raise ProviderError(f"AKShare returned no daily bars for {symbol}")
        mapping = {
            "日期": "date",
            "开盘": "open",
            "最高": "high",
            "最低": "low",
            "收盘": "close",
            "成交量": "volume",
            "成交额": "amount",
            "换手率": "turnover",
        }
        missing = [
            key
            for key in ("日期", "开盘", "最高", "最低", "收盘", "成交量")
            if key not in raw.columns
        ]
        if missing:
            raise ProviderError(f"AKShare schema changed; missing columns: {missing}")
        return normalize_ohlcv(raw.rename(columns=mapping))


def _bs_code(symbol: str) -> str:
    clean = symbol.lower().replace("sh.", "").replace("sz.", "").replace("bj.", "")
    if len(clean) != 6 or not clean.isdigit():
        raise ProviderError(f"unsupported A-share symbol: {symbol}")
    if clean.startswith(("5", "6", "9")):
        return f"sh.{clean}"
    if clean.startswith(("0", "1", "2", "3")):
        return f"sz.{clean}"
    raise ProviderError(f"cannot infer exchange for {symbol}")


class BaoStockProvider:
    name = "baostock"

    def get_daily_bars(
        self,
        symbol: str,
        start: date,
        end: date,
        adjust: str = "qfq",
    ) -> pd.DataFrame:
        try:
            import baostock as bs
        except ImportError as exc:
            raise ProviderError("baostock is not installed") from exc
        adjust_map = {"": "3", "none": "3", "qfq": "2", "hfq": "1"}
        adjustflag = adjust_map.get(adjust)
        if adjustflag is None:
            raise ProviderError(f"unsupported adjust mode: {adjust}")
        login = bs.login()
        if login.error_code != "0":
            raise ProviderError(f"BaoStock login failed: {login.error_msg}")
        try:
            fields = "date,open,high,low,close,volume,amount,turn"
            rs = bs.query_history_k_data_plus(
                _bs_code(symbol),
                fields,
                start_date=start.isoformat(),
                end_date=end.isoformat(),
                frequency="d",
                adjustflag=adjustflag,
            )
            if rs.error_code != "0":
                raise ProviderError(f"BaoStock query failed: {rs.error_msg}")
            rows: list[list[str]] = []
            while rs.next():
                rows.append(rs.get_row_data())
            raw = pd.DataFrame(rows, columns=rs.fields)
        finally:
            bs.logout()
        if raw.empty:
            raise ProviderError(f"BaoStock returned no daily bars for {symbol}")
        return normalize_ohlcv(raw.rename(columns={"turn": "turnover"}))


def _sina_stock_code(symbol: str) -> str:
    clean = symbol.lower().replace("sh.", "").replace("sz.", "").replace("bj.", "")
    if len(clean) != 6 or not clean.isdigit():
        raise ProviderError(f"unsupported A-share symbol: {symbol}")
    if clean.startswith("6"):
        return f"sh{clean}"
    if clean.startswith(("0", "1", "2", "3")):
        return f"sz{clean}"
    raise ProviderError(f"financial adapter only supports Shanghai/Shenzhen A shares: {symbol}")


class AKShareResearchProvider:
    name = "akshare"

    @staticmethod
    def _ak():
        try:
            import akshare as ak
        except ImportError as exc:
            raise ProviderError("akshare is not installed") from exc
        return ak

    def get_company_profile(self, symbol: str) -> dict[str, object]:
        ak = self._ak()
        errors: list[str] = []
        profile: dict[str, object] = {}
        try:
            raw = ak.stock_profile_cninfo(symbol=symbol)
            if raw is not None and not raw.empty:
                profile.update(raw.iloc[0].to_dict())
        except Exception as exc:
            errors.append(f"stock_profile_cninfo={exc}")
        try:
            raw = ak.stock_individual_info_em(symbol=symbol)
            if raw is not None and not raw.empty and {"item", "value"}.issubset(raw.columns):
                profile.update(dict(zip(raw["item"].astype(str), raw["value"])))
        except Exception as exc:
            errors.append(f"stock_individual_info_em={exc}")
        if profile:
            return profile
        raise ProviderError("company profile unavailable: " + "; ".join(errors))

    def get_financial_indicators(self, symbol: str, start_year: int) -> pd.DataFrame:
        ak = self._ak()
        raw = ak.stock_financial_analysis_indicator(symbol=symbol, start_year=str(start_year))
        if raw is None or raw.empty:
            raise ProviderError(f"financial indicators unavailable for {symbol}")
        return raw.copy()

    def get_financial_statements(self, symbol: str) -> dict[str, pd.DataFrame]:
        ak = self._ak()
        stock = _sina_stock_code(symbol)
        result: dict[str, pd.DataFrame] = {}
        errors: list[str] = []
        for key, statement_name in (
            ("balance", "资产负债表"),
            ("profit", "利润表"),
            ("cashflow", "现金流量表"),
        ):
            try:
                raw = ak.stock_financial_report_sina(stock=stock, symbol=statement_name)
                if raw is not None and not raw.empty:
                    result[key] = raw.copy()
                else:
                    errors.append(f"{statement_name}=empty")
            except Exception as exc:
                errors.append(f"{statement_name}={exc}")
        if not result:
            raise ProviderError("financial statements unavailable: " + "; ".join(errors))
        return result

    def get_valuation_history(self, symbol: str) -> pd.DataFrame:
        ak = self._ak()
        raw = ak.stock_value_em(symbol=symbol)
        if raw is None or raw.empty:
            raise ProviderError(f"valuation history unavailable for {symbol}")
        return raw.copy()

    def get_disclosures(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        ak = self._ak()
        raw = ak.stock_zh_a_disclosure_report_cninfo(
            symbol=symbol,
            market="沪深京",
            keyword="",
            category="",
            start_date=start.strftime("%Y%m%d"),
            end_date=end.strftime("%Y%m%d"),
        )
        if raw is None:
            return pd.DataFrame(columns=["代码", "简称", "公告标题", "公告时间", "公告链接"])
        return raw.copy()

    def get_index_daily(self, index_symbol: str, start: date, end: date) -> pd.DataFrame:
        ak = self._ak()
        raw = ak.stock_zh_index_daily_em(
            symbol=index_symbol,
            start_date=start.strftime("%Y%m%d"),
            end_date=end.strftime("%Y%m%d"),
        )
        if raw is None or raw.empty:
            raise ProviderError(f"index bars unavailable for {index_symbol}")
        frame = raw.rename(
            columns={
                "日期": "date",
                "开盘": "open",
                "最高": "high",
                "最低": "low",
                "收盘": "close",
                "成交量": "volume",
                "成交额": "amount",
            }
        )
        return normalize_ohlcv(frame)

    def get_industry_daily(self, industry_name: str, start: date, end: date) -> pd.DataFrame:
        ak = self._ak()
        raw = ak.stock_board_industry_hist_em(
            symbol=industry_name,
            start_date=start.strftime("%Y%m%d"),
            end_date=end.strftime("%Y%m%d"),
            period="日k",
            adjust="",
        )
        if raw is None or raw.empty:
            raise ProviderError(f"industry bars unavailable for {industry_name}")
        frame = raw.rename(
            columns={
                "日期": "date",
                "开盘": "open",
                "最高": "high",
                "最低": "low",
                "收盘": "close",
                "成交量": "volume",
                "成交额": "amount",
                "换手率": "turnover",
            }
        )
        return normalize_ohlcv(frame)

    def get_industry_constituents(self, industry_name: str) -> pd.DataFrame:
        ak = self._ak()
        raw = ak.stock_board_industry_cons_em(symbol=industry_name)
        if raw is None or raw.empty:
            raise ProviderError(f"industry constituents unavailable for {industry_name}")
        return raw.copy()
