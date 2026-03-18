"""Format conversion: .sav → xlsx, csv, dta, parquet."""

import io
import logging
import os
import tempfile

import pandas as pd
import pyreadstat

logger = logging.getLogger(__name__)


class FormatConverter:
    """Convert SPSS .sav files to other formats."""

    @staticmethod
    def convert(
        df: pd.DataFrame,
        meta,
        target_format: str,
        apply_labels: bool = True,
        include_metadata_sheet: bool = True,
    ) -> tuple[bytes, str, str]:
        """Convert a DataFrame + metadata to target format.

        Returns:
            Tuple of (file_bytes, content_type, file_extension)
        """
        if apply_labels:
            df = FormatConverter._apply_value_labels(df, meta)

        if target_format == "csv":
            return FormatConverter._to_csv(df), "text/csv", ".csv"
        elif target_format == "xlsx":
            return FormatConverter._to_xlsx(df, meta, include_metadata_sheet), \
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", ".xlsx"
        elif target_format == "dta":
            return FormatConverter._to_stata(df, meta), "application/x-stata", ".dta"
        elif target_format == "parquet":
            return FormatConverter._to_parquet(df), "application/octet-stream", ".parquet"
        else:
            raise ValueError(f"Unsupported target format: {target_format}")

    @staticmethod
    def _apply_value_labels(df: pd.DataFrame, meta) -> pd.DataFrame:
        """Replace numeric codes with value labels where available."""
        df = df.copy()
        value_labels = getattr(meta, "variable_value_labels", {})
        for col, labels in value_labels.items():
            if col in df.columns and labels:
                df[col] = df[col].map(lambda x, lbl=labels: lbl.get(x, x))
        return df

    @staticmethod
    def _to_csv(df: pd.DataFrame) -> bytes:
        buf = io.BytesIO()
        df.to_csv(buf, index=False, encoding="utf-8-sig")
        return buf.getvalue()

    @staticmethod
    def _to_xlsx(df: pd.DataFrame, meta, include_metadata_sheet: bool) -> bytes:
        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as writer:
            df.to_excel(writer, sheet_name="Data", index=False)

            if include_metadata_sheet and meta:
                col_labels = getattr(meta, "column_names_to_labels", {})
                if col_labels:
                    meta_df = pd.DataFrame([
                        {"Variable": name, "Label": label}
                        for name, label in col_labels.items()
                    ])
                    meta_df.to_excel(writer, sheet_name="Variable Labels", index=False)
        return buf.getvalue()

    @staticmethod
    def _to_stata(df: pd.DataFrame, meta) -> bytes:
        df = df.copy()
        df.columns = [c.replace(" ", "_").replace(".", "_")[:32] for c in df.columns]

        col_labels = {}
        if meta:
            raw_labels = getattr(meta, "column_names_to_labels", {})
            for orig, new in zip(getattr(meta, "column_names", df.columns), df.columns):
                if orig in raw_labels:
                    col_labels[new] = raw_labels[orig][:80]

        # Use mkstemp to avoid Windows file locking issues with NamedTemporaryFile
        fd, tmp_path = tempfile.mkstemp(suffix=".dta")
        os.close(fd)
        try:
            pyreadstat.write_dta(df, tmp_path, column_labels=col_labels)
            with open(tmp_path, "rb") as f:
                return f.read()
        finally:
            os.unlink(tmp_path)

    @staticmethod
    def _to_parquet(df: pd.DataFrame) -> bytes:
        try:
            buf = io.BytesIO()
            df.to_parquet(buf, index=False, engine="pyarrow")
            return buf.getvalue()
        except ImportError:
            raise ValueError("Parquet export requires pyarrow. Install with: pip install pyarrow")
